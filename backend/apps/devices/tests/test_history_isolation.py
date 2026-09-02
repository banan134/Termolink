"""feature_values is isolated through a security_barrier view (docs/03) — tested as the app role."""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.devices.models import Device, FeatureValue
from apps.providers.models import ProviderAccount
from apps.tenants.context import ANONYMOUS, ROLE_OPERATOR, SYSTEM, TenantContext, set_context
from apps.tenants.models import Tenant


def make_device(tenant: Tenant, name: str) -> Device:
    account = ProviderAccount.objects.create(
        tenant=tenant, provider="viessmann", refresh_token_enc=b"v1|x"
    )
    return Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": name, "deviceId": "0"},
        display_name=name,
    )


@pytest.fixture
def as_app_role() -> Iterator[None]:
    with connection.cursor() as cursor:
        cursor.execute(f'SET LOCAL ROLE "{settings.DB_APP_USER}"')
    yield


def count_rows(table: str = "feature_values_rls") -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 — constant
        return int(cursor.fetchone()[0])


@pytest.mark.django_db
def test_view_isolates_history_and_checks_inserts(as_app_role: None) -> None:
    set_context(SYSTEM)
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    da, db = make_device(a, "A1"), make_device(b, "B1")
    now = timezone.now()
    FeatureValue.objects.bulk_create(
        [
            FeatureValue(
                tenant=a,
                device=da,
                feature_name="f",
                property_name="v",
                ts_polled=now,
                value_num=1.0,
            ),
            FeatureValue(
                tenant=b,
                device=db,
                feature_name="f",
                property_name="v",
                ts_polled=now,
                value_num=2.0,
            ),
        ]
    )
    assert count_rows() == 2

    set_context(TenantContext(role="tenant", tenant_id=a.id))
    assert count_rows() == 1
    assert list(FeatureValue.objects.values_list("value_num", flat=True)) == [1.0]
    with pytest.raises(DatabaseError), transaction.atomic():
        # WITH CHECK OPTION: tenant A cannot write rows for tenant B
        FeatureValue.objects.create(
            tenant=b, device=db, feature_name="f", property_name="v", ts_polled=now, value_num=3.0
        )
    FeatureValue.objects.create(
        tenant=a, device=da, feature_name="f", property_name="v2", ts_polled=now, value_num=4.0
    )
    assert count_rows() == 2

    set_context(TenantContext(role=ROLE_OPERATOR, allowed_tenants=(b.id,)))
    assert count_rows() == 1 and list(FeatureValue.objects.values_list("value_num", flat=True)) == [
        2.0
    ]
    set_context(ANONYMOUS)
    assert count_rows() == 0

    # the raw hypertable and the raw aggregates are out of reach for the app role
    for table in ("feature_values", "feature_values_1h", "feature_values_1d"):
        with pytest.raises(DatabaseError), transaction.atomic():
            count_rows(table)
    set_context(SYSTEM)
    assert count_rows("feature_values_1h_rls") == 0  # empty but readable


@pytest.mark.django_db
def test_hypertable_and_compression_are_configured() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT compression_enabled FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'feature_values'"
        )
        row = cursor.fetchone()
        assert row is not None and row[0] is True
        cursor.execute(
            "SELECT view_name FROM timescaledb_information.continuous_aggregates ORDER BY view_name"
        )
        assert [r[0] for r in cursor.fetchall()] == ["feature_values_1d", "feature_values_1h"]
