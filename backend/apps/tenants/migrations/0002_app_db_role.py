"""Create the runtime DB role (LOGIN, NOBYPASSRLS) — docs/03 §Izolacja.

Runs as the owner role (DJANGO_DB_ROLE=admin). The same routine is re-run on every backend
start by `manage.py ensure_app_db_role`, so password changes in .env take effect.
"""

from django.db import migrations

from apps.tenants.dbrole import ensure_app_role


def create_app_role(apps, schema_editor):  # type: ignore[no-untyped-def]
    with schema_editor.connection.cursor() as cursor:
        ensure_app_role(cursor, schema_editor.connection.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0001_initial"),
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(create_app_role, migrations.RunPython.noop),
    ]
