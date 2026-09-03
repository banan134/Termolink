"""RLS on alert_rules and alerts (alerts may be tenant-less: operator/worker alerts)."""

from django.db import migrations

from apps.tenants.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0001_initial"),
        ("tenants", "0004_rls_user_sessions"),
    ]

    operations = rls_operations("alert_rules") + rls_operations("alerts", tenant_nullable=True)
