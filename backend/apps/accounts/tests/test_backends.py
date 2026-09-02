import pytest
from django.contrib.auth import authenticate
from django.db import connection, transaction

from apps.accounts.models import Role, User
from apps.tenants.context import ANONYMOUS, current_context, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.mark.django_db
def test_authenticate_works_under_rls_role_and_restores_context() -> None:
    tenant = Tenant.objects.create(name="A")
    User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET LOCAL ROLE "termolink_app"')
        set_context(ANONYMOUS)
        user = authenticate(None, username="u@example.com", password=PASSWORD)
        assert user is not None and user.email == "u@example.com"
        assert authenticate(None, username="u@example.com", password="wrong") is None
        # the privileged window is closed again
        assert current_context()["role"] == "anonymous"
