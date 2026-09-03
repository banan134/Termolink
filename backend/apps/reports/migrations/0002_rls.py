"""RLS on report_schedules and report_files."""

from django.db import migrations

from apps.tenants.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
        ("tenants", "0004_rls_user_sessions"),
    ]

    operations = rls_operations("report_schedules") + rls_operations("report_files")
