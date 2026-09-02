"""RLS tested for real: as the runtime role `termolink_app`, without WHERE tenant_id (docs/12)."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction

from apps.accounts.models import Invitation, Role, User
from apps.tenants.context import (
    ANONYMOUS,
    ROLE_OPERATOR,
    SYSTEM,
    TenantContext,
    set_context,
)
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "correct-horse-battery-staple"


@dataclass
class Data:
    a: Tenant
    b: Tenant
    tech: User


@pytest.fixture
def data() -> Data:
    a = Tenant.objects.create(name="A")
    b = Tenant.objects.create(name="B")
    tech = User.objects.create_user("tech@example.com", PASSWORD, role=Role.TECHNICIAN)
    TenantMembership.objects.create(user=tech, tenant=a)
    TenantMembership.objects.create(user=tech, tenant=b)
    User.objects.create_user("ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=a)
    User.objects.create_user("ub@example.com", PASSWORD, role=Role.TENANT_USER, tenant=b)
    Invitation.issue(email="ia@example.com", role=Role.TENANT_USER, tenant=a, created_by=None)
    Invitation.issue(email="it@example.com", role=Role.TECHNICIAN, tenant=None, created_by=None)
    return Data(a=a, b=b, tech=tech)


@pytest.fixture
def as_app_role() -> Iterator[None]:
    """Switch the (superuser) test connection to the runtime role for the rest of the test."""
    with connection.cursor() as cursor:
        cursor.execute(f'SET LOCAL ROLE "{settings.DB_APP_USER}"')
    yield


def tenant_ids(table: str) -> set[UUID | None]:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT tenant_id FROM {table}")  # noqa: S608 — constant table names
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_superuser_connection_bypasses_rls_which_is_why_the_app_uses_its_own_role(
    data: Data,
) -> None:
    set_context(ANONYMOUS)
    assert len(tenant_ids("tenant_memberships")) == 2


@pytest.mark.django_db
def test_tenant_context_sees_only_own_rows(data: Data, as_app_role: None) -> None:
    a, b = data.a, data.b
    set_context(TenantContext(role="tenant", tenant_id=a.id))
    assert tenant_ids("tenant_memberships") == {a.id}
    assert tenant_ids("users") == {a.id}
    assert tenant_ids("invitations") == {a.id}
    assert TenantMembership.objects.filter(tenant=b).count() == 0


@pytest.mark.django_db
def test_operator_sees_allowed_tenants_and_global_rows(data: Data, as_app_role: None) -> None:
    a, b = data.a, data.b
    set_context(TenantContext(role=ROLE_OPERATOR, allowed_tenants=(a.id,)))
    assert tenant_ids("tenant_memberships") == {a.id}
    # operator accounts (tenant_id IS NULL) stay visible to operators
    assert tenant_ids("users") == {a.id, None}
    assert tenant_ids("invitations") == {a.id, None}
    set_context(TenantContext(role=ROLE_OPERATOR, allowed_tenants=(a.id, b.id)))
    assert tenant_ids("tenant_memberships") == {a.id, b.id}


@pytest.mark.django_db
def test_anonymous_and_missing_context_see_nothing(data: Data, as_app_role: None) -> None:
    set_context(ANONYMOUS)
    assert tenant_ids("tenant_memberships") == set()
    assert tenant_ids("users") == set()


@pytest.mark.django_db
def test_system_context_sees_everything(data: Data, as_app_role: None) -> None:
    set_context(SYSTEM)
    assert len(tenant_ids("tenant_memberships")) == 2
    assert len(tenant_ids("users")) == 3


@pytest.mark.django_db
def test_write_into_other_tenant_is_rejected(data: Data, as_app_role: None) -> None:
    a, b, tech = data.a, data.b, data.tech
    set_context(TenantContext(role="tenant", tenant_id=a.id))
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
                "created_at) VALUES (gen_random_uuid(), %s, 'x@example.com', 'tenant_user', 'h', "
                "now() + interval '1 day', now())",
                [b.id],
            )
    # the same row for the own tenant is fine
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
            "created_at) VALUES (gen_random_uuid(), %s, 'y@example.com', 'tenant_user', 'h2', "
            "now() + interval '1 day', now())",
            [a.id],
        )
    assert tech is not None
