"""`manage.py run_worker [--concurrency N] [--tick S] [--once]` (docs/15)."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from apps.ingest.worker import Worker


class Command(BaseCommand):
    help = "Run the Termolink background worker (job queue in PostgreSQL)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--concurrency", type=int, default=4)
        parser.add_argument("--tick", type=float, default=5.0, help="seconds between ticks")
        parser.add_argument("--once", action="store_true", help="run a single tick and exit")

    def handle(self, *args: Any, **options: Any) -> None:
        worker = Worker(concurrency=options["concurrency"], tick=options["tick"])
        if options["once"]:
            ran = worker.run_once()
            self.stdout.write(f"tick done: {ran} job(s) run")
            worker.shutdown()
            return
        try:
            worker.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            worker.shutdown()
