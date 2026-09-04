"""Permanent deletion of tenants and devices (operator request, 2026-09-04)."""

from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.devices.models import Device, FeatureLatest, FeatureValue
from apps.providers.models import ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


def _login(user: User) -> Client:
    c = Client()
    user.totp_enabled = False
    user.save(update_fields=["totp_enabled"])
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    return c


def _world() -> dict[str, Any]:
    tenant = Tenant.objects.create(name="Do usunięcia")
    account = ProviderAccount.objects.create(tenant=tenant, provider="viessmann")
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"deviceId": "0"},
        display_name="Kociol",
    )
    FeatureValue.objects.create(
        tenant=tenant,
        device=device,
        feature_name="f",
        property_name="value",
        ts_polled=timezone.now(),
        value_num=1.0,
    )
    FeatureLatest.objects.create(
        tenant=tenant,
        device=device,
        feature_name="f",
        property_name="value",
        value_num=1.0,
        ts_polled=timezone.now(),
    )
    User.objects.create_user("ta@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant)
    return {"tenant": tenant, "device": device}


def _history_rows(**where: Any) -> int:
    col, val = next(iter(where.items()))
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM feature_values WHERE {col} = %s", [val])  # noqa: S608
        return int(cursor.fetchone()[0])


@pytest.mark.django_db
def test_superadmin_deletes_tenant_with_everything() -> None:
    w = _world()
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    tid = w["tenant"].id
    assert _login(tech).delete(f"/api/v1/admin/tenants/{tid}").status_code in (403, 404)
    r = _login(sa).delete(f"/api/v1/admin/tenants/{tid}")
    assert r.status_code == 204
    assert not Tenant.objects.filter(id=tid).exists()
    assert not Device.objects.filter(tenant_id=tid).exists()
    assert not User.objects.filter(email="ta@example.com").exists()
    assert _history_rows(tenant_id=tid) == 0
    entry = AuditLog.objects.filter(action="tenant.deleted").latest("ts")
    assert entry.details["name"] == "Do usunięcia" and entry.tenant_id is None


@pytest.mark.django_db
def test_operator_deletes_device_permanently_or_archives() -> None:
    w = _world()
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    c = _login(sa)
    tid, did = w["tenant"].id, w["device"].id
    assert c.delete(f"/api/v1/tenants/{tid}/devices/{did}").status_code == 204  # archive
    assert Device.objects.get(id=did).archived_at is not None
    assert c.delete(f"/api/v1/tenants/{tid}/devices/{did}?permanent=1").status_code == 204
    assert not Device.objects.filter(id=did).exists()
    assert _history_rows(device_id=did) == 0
    assert AuditLog.objects.filter(action="device.deleted").exists()
