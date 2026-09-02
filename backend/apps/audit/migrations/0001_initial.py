import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.tenants.dbrole import ensure_app_role
from apps.tenants.rls import rls_operations


def apply_app_role_grants(apps, schema_editor):  # type: ignore[no-untyped-def]
    with schema_editor.connection.cursor() as cursor:
        ensure_app_role(cursor, schema_editor.connection.connection)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0004_rls_user_sessions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("action", models.TextField()),
                ("target_type", models.TextField(blank=True, default="")),
                ("target_id", models.UUIDField(blank=True, null=True)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("ts", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "audit_log", "ordering": ["-ts"]},
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["tenant", "ts"], name="audit_log_tenant_ts"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["user", "ts"], name="audit_log_user_ts"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["action", "ts"], name="audit_log_action_ts"),
        ),
        *rls_operations("audit_log", tenant_nullable=True),
        # Append-only for the runtime role (re-applied on every start by ensure_app_db_role).
        migrations.RunPython(apply_app_role_grants, migrations.RunPython.noop),
    ]
