"""audit_log is append-only for the app role, so deleting a tenant/user must not require an
UPDATE from the application: the foreign keys get ON DELETE SET NULL at the database level
(referential-integrity actions run with the table owner's privileges)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = """
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT con.conname, att.attname
    FROM pg_constraint con
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
    WHERE con.conrelid = 'audit_log'::regclass AND con.contype = 'f'
      AND att.attname IN ('tenant_id', 'user_id')
  LOOP
    EXECUTE format('ALTER TABLE audit_log DROP CONSTRAINT %I', c.conname);
    IF c.attname = 'tenant_id' THEN
      EXECUTE format(
        'ALTER TABLE audit_log ADD CONSTRAINT %I FOREIGN KEY (tenant_id) REFERENCES tenants(id) '
        'ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED', c.conname);
    ELSE
      EXECUTE format(
        'ALTER TABLE audit_log ADD CONSTRAINT %I FOREIGN KEY (user_id) REFERENCES users(id) '
        'ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED', c.conname);
    END IF;
  END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop),
    ]
