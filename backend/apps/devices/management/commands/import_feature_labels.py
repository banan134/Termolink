"""`manage.py import_feature_labels [--replace] [--csv PATH]` — (re)load the labels dictionary."""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from apps.devices import labels


class Command(BaseCommand):
    help = "Import feature_labels from the bundled CSV (upsert; --replace wipes first)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--csv", default=str(labels.CSV_PATH))
        parser.add_argument("--replace", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        count = labels.import_csv(Path(options["csv"]), replace=options["replace"])
        self.stdout.write(f"feature_labels: {count} rows imported")
