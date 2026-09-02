"""RLS on jobs (docs/03); tenant_id NULL = global job."""

from django.db import migrations

from apps.tenants.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("ingest", "0001_initial"),
        ("tenants", "0004_rls_user_sessions"),
    ]

    operations = rls_operations("jobs", tenant_nullable=True)
