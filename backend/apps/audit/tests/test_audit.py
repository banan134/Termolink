import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.test import Client, RequestFactory

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.audit.services import audit
from apps.tenants.context import ANONYMOUS, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.mark.django_db
def test_audit_records_user_tenant_ip_and_target() -> None:
    tenant = Tenant.objects.create(name="A")
    user = User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1")
    request.user = user
    row = audit("test.action", request=request, target=tenant, details={"k": 1})
    assert row.user == user and row.tenant == tenant
    assert row.ip == "203.0.113.5"
    assert row.target_type == "tenants" and row.target_id == tenant.id
    assert row.details == {"k": 1}


@pytest.mark.django_db
def test_audit_works_from_anonymous_context_under_app_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute(f'SET LOCAL ROLE "{settings.DB_APP_USER}"')
    set_context(ANONYMOUS)
    audit("auth.login.failed", details={"email": "x@example.com"})
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM audit_log")
        assert cursor.fetchone()[0] == 0  # anonymous cannot read it back
    set_context(ANONYMOUS)


@pytest.mark.django_db
def test_audit_log_is_append_only_for_app_role() -> None:
    row = audit("x")
    with connection.cursor() as cursor:
        cursor.execute(f'SET LOCAL ROLE "{settings.DB_APP_USER}"')
    from apps.tenants.context import SYSTEM

    set_context(SYSTEM)
    for sql in (
        "UPDATE audit_log SET action = 'y' WHERE id = %s",
        "DELETE FROM audit_log WHERE id = %s",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [row.id])
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audit_log (action, target_type, details, ts) VALUES ('z', '', '{}', now())"
        )


@pytest.mark.django_db
def test_auth_events_are_audited() -> None:
    tenant = Tenant.objects.create(name="A")
    User.objects.create_user("jan@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    client = Client()
    client.post(
        "/api/v1/auth/login",
        {"email": "jan@example.com", "password": "nope"},
        content_type="application/json",
    )
    client.post(
        "/api/v1/auth/login",
        {"email": "jan@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    client.post("/api/v1/auth/logout")
    actions = list(AuditLog.objects.order_by("ts").values_list("action", flat=True))
    assert actions == ["auth.login.failed", "auth.login", "auth.logout"]
    failed = AuditLog.objects.get(action="auth.login.failed")
    assert failed.user is None and failed.details == {
        "email": "jan@example.com",
        "reason": "invalid_credentials",
    }
    assert AuditLog.objects.get(action="auth.login").tenant == tenant
