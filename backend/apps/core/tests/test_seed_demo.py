from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.accounts.models import Role, User
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "demo-password-1234"


@pytest.mark.django_db
@override_settings(DJANGO_ENV="dev", DEV_ADMIN_PASSWORD=PASSWORD)
def test_seed_demo_creates_everything_and_is_idempotent() -> None:
    out = StringIO()
    call_command("seed_demo", stdout=out)
    assert "NEW TOTP secret" in out.getvalue()
    admin = User.objects.get(email="admin@termolink.local")
    assert admin.role == Role.SUPERADMIN and admin.totp_enabled and admin.check_password(PASSWORD)
    assert Tenant.objects.count() == 2
    assert User.objects.filter(role=Role.TENANT_ADMIN).count() == 2
    assert User.objects.filter(role=Role.TENANT_USER).count() == 2
    tech = User.objects.get(email="serwis@termolink.local")
    assert TenantMembership.objects.filter(user=tech, can_control=True).count() == 1

    secret_before = bytes(admin.totp_secret_enc or b"")
    out = StringIO()
    call_command("seed_demo", stdout=out)
    assert "secret unchanged" in out.getvalue()
    assert Tenant.objects.count() == 2 and User.objects.count() == 6
    admin.refresh_from_db()
    assert bytes(admin.totp_secret_enc or b"") == secret_before


@pytest.mark.django_db
@override_settings(DJANGO_ENV="prod", DEV_ADMIN_PASSWORD=PASSWORD)
def test_seed_demo_refuses_outside_dev() -> None:
    with pytest.raises(CommandError):
        call_command("seed_demo")
    assert User.objects.count() == 0


@pytest.mark.django_db
@override_settings(DJANGO_ENV="dev", DEV_ADMIN_PASSWORD="short")
def test_seed_demo_requires_password() -> None:
    with pytest.raises(CommandError):
        call_command("seed_demo")
