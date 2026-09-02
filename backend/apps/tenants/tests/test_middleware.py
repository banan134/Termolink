import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.accounts.models import Role, User
from apps.tenants.context import current_context, set_context
from apps.tenants.middleware import TenantContextMiddleware
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "correct-horse-battery-staple"


def run(user: object) -> dict[str, str | None]:
    seen: dict[str, str | None] = {}

    def view(request: HttpRequest) -> HttpResponse:
        seen.update(current_context())
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.user = user  # type: ignore[assignment]
    TenantContextMiddleware(view)(request)
    return seen


@pytest.mark.django_db
def test_anonymous_request_gets_anonymous_context() -> None:
    ctx = run(AnonymousUser())
    assert ctx["role"] == "anonymous"
    assert ctx["tenant_id"] == ""
    assert ctx["allowed_tenants"] == ""


@pytest.mark.django_db
def test_tenant_user_gets_tenant_context() -> None:
    tenant = Tenant.objects.create(name="A")
    user = User.objects.create_user(
        "u@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    ctx = run(user)
    assert ctx["role"] == "tenant"
    assert ctx["tenant_id"] == str(tenant.id)
    assert ctx["user_id"] == str(user.id)


@pytest.mark.django_db
def test_technician_gets_membership_tenants() -> None:
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    TenantMembership.objects.create(user=tech, tenant=a)
    ctx = run(tech)
    assert ctx["role"] == "operator"
    assert ctx["allowed_tenants"] == str(a.id)
    assert str(b.id) not in (ctx["allowed_tenants"] or "")


@pytest.mark.django_db
def test_superadmin_gets_all_tenants() -> None:
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    ctx = run(admin)
    assert ctx["role"] == "operator"
    assert set((ctx["allowed_tenants"] or "").split(",")) == {str(a.id), str(b.id)}


@pytest.mark.django_db
def test_context_is_transaction_local() -> None:
    from apps.tenants.context import ANONYMOUS

    set_context(ANONYMOUS)
    assert current_context()["role"] == "anonymous"


def test_set_context_requires_transaction() -> None:
    from django.db import connection

    from apps.tenants.context import ANONYMOUS

    if connection.in_atomic_block:
        pytest.skip("already inside a transaction")
    with pytest.raises(RuntimeError):
        set_context(ANONYMOUS)


@pytest.mark.django_db
def test_login_inside_request_switches_context_and_updates_last_login() -> None:
    from django.contrib.auth import login, logout
    from django.contrib.sessions.middleware import SessionMiddleware

    tenant = Tenant.objects.create(name="A")
    user = User.objects.create_user("l@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    seen: dict[str, str | None] = {}

    def view(request: HttpRequest) -> HttpResponse:
        login(request, user, backend="apps.accounts.backends.RlsModelBackend")
        seen.update(current_context())
        logout(request)
        seen["after_logout"] = current_context()["role"]
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = AnonymousUser()
    TenantContextMiddleware(view)(request)
    assert seen["role"] == "tenant" and seen["tenant_id"] == str(tenant.id)
    assert seen["after_logout"] == "anonymous"
    user.refresh_from_db()
    assert user.last_login is not None
