import pytest
from django.db import IntegrityError

from apps.accounts.models import Role, User
from apps.tenants.models import Tenant, TenantMembership


@pytest.mark.django_db
def test_tenant_defaults() -> None:
    tenant = Tenant.objects.create(name="Klient A")
    assert tenant.control_allowed is True
    assert tenant.timezone == "Europe/Warsaw"
    assert tenant.type == "company"
    assert tenant.is_archived is False


@pytest.mark.django_db
def test_membership_is_unique_per_user_and_tenant() -> None:
    tenant = Tenant.objects.create(name="Klient A")
    tech = User.objects.create_user(
        "tech@example.com", "correct-horse-battery", role=Role.TECHNICIAN
    )
    TenantMembership.objects.create(user=tech, tenant=tenant, can_control=True)
    with pytest.raises(IntegrityError):
        TenantMembership.objects.create(user=tech, tenant=tenant)
