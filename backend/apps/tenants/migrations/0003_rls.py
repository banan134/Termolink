"""Enable row-level security on every table carrying tenant_id (docs/03)."""

from django.db import migrations

from apps.tenants.rls import RLS_TABLES, rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_app_db_role"),
    ]

    operations = [
        op
        for table, nullable in RLS_TABLES.items()
        for op in rls_operations(table, tenant_nullable=nullable)
    ]
