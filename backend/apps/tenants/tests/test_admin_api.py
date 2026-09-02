import pytest
from django.core import mail
from django.test import Client

from apps.accounts.models import Invitation, Role, User
from apps.audit.models import AuditLog
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "correct-horse-battery-staple"


def login(email: str) -> Client:
    client = Client()
    r = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return client


@pytest.fixture
def superadmin() -> User:
    u = User.objects.create_superuser("sa@example.com", PASSWORD)
    return u


def gate_off(user: User) -> None:
    """Operators are gated without 2FA — flip the flag after login for API tests."""
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])


@pytest.mark.django_db
def test_superadmin_creates_lists_and_edits_tenants(superadmin: User) -> None:
    client = login(superadmin.email)
    gate_off(superadmin)
    r = client.post(
        "/api/v1/admin/tenants",
        {"name": "Klient X", "type": "person"},
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    tid = r.json()["id"]
    assert r.json()["users_count"] == 0 and r.json()["control_allowed"] is True

    r = client.get("/api/v1/admin/tenants")
    assert r.status_code == 200 and r.json()["count"] == 1

    r = client.patch(
        f"/api/v1/admin/tenants/{tid}",
        {"control_allowed": False, "report_header_text": "Klient X sp. z o.o."},
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["control_allowed"] is False
    assert list(AuditLog.objects.order_by("ts").values_list("action", flat=True))[-2:] == [
        "tenant.created",
        "tenant.updated",
    ]


@pytest.mark.django_db
def test_technician_sees_only_memberships_and_cannot_create(superadmin: User) -> None:
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    TenantMembership.objects.create(user=tech, tenant=a)
    client = login(tech.email)
    gate_off(tech)
    names = [t["name"] for t in client.get("/api/v1/admin/tenants").json()["results"]]
    assert names == ["A"]
    assert client.get(f"/api/v1/admin/tenants/{b.id}").status_code == 404
    r = client.post("/api/v1/admin/tenants", {"name": "C"}, content_type="application/json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_invitations_from_operator_and_tenant_admin(superadmin: User) -> None:
    tenant = Tenant.objects.create(name="A")
    admin = User.objects.create_user(
        "aa@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    client = login(superadmin.email)
    gate_off(superadmin)
    r = client.post(
        f"/api/v1/admin/tenants/{tenant.id}/invitations",
        {"email": "One@example.com", "role": "tenant_user"},
        content_type="application/json",
    )
    assert r.status_code == 201 and len(mail.outbox) == 1
    assert "/invite/" in mail.outbox[0].body

    ta = login(admin.email)
    r = ta.post(
        f"/api/v1/tenants/{tenant.id}/invitations",
        {"email": "two@example.com", "role": "tenant_admin"},
        content_type="application/json",
    )
    assert r.status_code == 201
    r = ta.post(
        f"/api/v1/tenants/{tenant.id}/invitations",
        {"email": "aa@example.com", "role": "tenant_user"},
        content_type="application/json",
    )
    assert r.status_code == 409  # already a user
    r = ta.post(
        f"/api/v1/tenants/{tenant.id}/invitations",
        {"email": "x@example.com", "role": "superadmin"},
        content_type="application/json",
    )
    assert r.status_code == 400

    users = ta.get(f"/api/v1/tenants/{tenant.id}/users").json()
    assert users["count"] == 1 and {i["email"] for i in users["invitations"]} == {
        "one@example.com",
        "two@example.com",
    }
    assert Invitation.objects.filter(tenant=tenant).count() == 2


@pytest.mark.django_db
def test_tenant_user_cannot_list_or_invite(superadmin: User) -> None:
    tenant = Tenant.objects.create(name="A")
    User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    client = login("u@example.com")
    assert client.get(f"/api/v1/tenants/{tenant.id}/users").status_code == 403
    assert client.get("/api/v1/admin/tenants").status_code == 403


@pytest.mark.django_db
def test_memberships_management(superadmin: User) -> None:
    a = Tenant.objects.create(name="A")
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    client = login(superadmin.email)
    gate_off(superadmin)
    assert client.get("/api/v1/admin/technicians").json()["count"] == 1
    r = client.post(
        f"/api/v1/admin/technicians/{tech.id}/memberships",
        {"tenant_id": str(a.id), "can_control": True},
        content_type="application/json",
    )
    assert r.status_code == 201 and r.json()["can_control"] is True
    assert client.get(f"/api/v1/admin/technicians/{tech.id}/memberships").json()["count"] == 1
    assert (
        client.delete(f"/api/v1/admin/technicians/{tech.id}/memberships/{a.id}").status_code == 204
    )
    assert (
        client.delete(f"/api/v1/admin/technicians/{tech.id}/memberships/{a.id}").status_code == 404
    )
    assert client.get(f"/api/v1/admin/technicians/{superadmin.id}/memberships").status_code == 404
