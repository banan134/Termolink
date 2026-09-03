from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import Invitation, Role, User, hash_token
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Klient A")


@pytest.mark.django_db
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"])
def test_passwords_are_hashed_with_argon2() -> None:
    user = User.objects.create_superuser("admin@example.com", PASSWORD)
    assert user.password.startswith("argon2")
    assert user.check_password(PASSWORD)
    assert user.is_staff and user.is_superuser and user.is_operator


@pytest.mark.django_db
def test_email_is_unique_case_insensitively(tenant: Tenant) -> None:
    User.objects.create_user("Jan@Example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    assert User.objects.get().email == "jan@example.com"
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="JAN@example.com", role=Role.TENANT_USER, tenant=tenant)


@pytest.mark.django_db
def test_operator_roles_must_not_have_tenant(tenant: Tenant) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="t@example.com", role=Role.TECHNICIAN, tenant=tenant)


@pytest.mark.django_db
def test_tenant_roles_require_tenant() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="u@example.com", role=Role.TENANT_ADMIN, tenant=None)


@pytest.mark.django_db
def test_create_user_validates_role_tenant_rule(tenant: Tenant) -> None:
    with pytest.raises(ValueError):
        User.objects.create_user("x@example.com", PASSWORD, role=Role.SUPERADMIN, tenant=tenant)


@pytest.mark.django_db
def test_invitation_issue_returns_raw_token_and_stores_hash(tenant: Tenant) -> None:
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    invitation, token = Invitation.issue(
        email="Nowy@Example.com", role=Role.TENANT_ADMIN, tenant=tenant, created_by=admin
    )
    assert invitation.email == "nowy@example.com"
    assert invitation.token_hash == hash_token(token)
    assert token not in invitation.token_hash
    assert invitation.is_valid
    assert timedelta(hours=71) < invitation.expires_at - timezone.now() <= timedelta(hours=72)


@pytest.mark.django_db
def test_invitation_expires_and_is_single_use(tenant: Tenant) -> None:
    invitation, _ = Invitation.issue(
        email="a@example.com", role=Role.TENANT_USER, tenant=tenant, created_by=None
    )
    invitation.accepted_at = timezone.now()
    assert not invitation.is_valid
    invitation.accepted_at = None
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    assert not invitation.is_valid
