"""Enable row-level security on every table carrying tenant_id (docs/03)."""

from django.db import migrations

from apps.tenants.rls import rls_operations

# Frozen here on purpose: later tables get their own migration (never iterate the live registry).
TABLES = {"users": True, "invitations": True, "tenant_memberships": False}


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_app_db_role"),
    ]

    operations = [
        op for table, nullable in TABLES.items() for op in rls_operations(table, tenant_nullable=nullable)
    ]
