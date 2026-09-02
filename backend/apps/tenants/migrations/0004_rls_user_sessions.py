"""RLS on user_sessions (docs/03)."""

from django.db import migrations

from apps.tenants.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_rls"),
        ("accounts", "0003_login_attempts_user_sessions"),
    ]

    operations = rls_operations("user_sessions", tenant_nullable=True)
