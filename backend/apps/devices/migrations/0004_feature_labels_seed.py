"""Initial feature_labels dictionary from the bundled CSV (docs/13 stage 3). Idempotent upsert."""

from django.db import migrations


def load_csv(apps, schema_editor):  # type: ignore[no-untyped-def]
    from apps.devices import labels

    labels.import_csv()


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0003_feature_labels"),
    ]

    operations = [
        migrations.RunPython(load_csv, migrations.RunPython.noop),
    ]
