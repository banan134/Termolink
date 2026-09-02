"""Enable the TimescaleDB extension (docs/03). Hypertables come in stage 2."""

from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS timescaledb;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
