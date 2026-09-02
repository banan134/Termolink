"""Background worker entry point.

Stage 1, task 1: a placeholder loop that only logs a heartbeat, so the `worker` service in
Compose and the Makefile match docs/15. The DB-backed job queue (`jobs`, SKIP LOCKED) and
`worker_heartbeats` arrive in stage 1, task 8 (docs/02, docs/06).
"""

import logging
import time
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection

log = logging.getLogger("termolink.worker")


class Command(BaseCommand):
    help = "Run the Termolink background worker (placeholder until the job queue exists)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--concurrency", type=int, default=4)
        parser.add_argument("--tick", type=float, default=5.0, help="seconds between ticks")
        parser.add_argument("--once", action="store_true", help="run a single tick and exit")

    def handle(self, *args: Any, **options: Any) -> None:
        tick: float = options["tick"]
        log.info("worker starting (concurrency=%s, tick=%ss)", options["concurrency"], tick)
        while True:
            self._heartbeat()
            if options["once"]:
                return
            time.sleep(tick)

    def _heartbeat(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        log.info("heartbeat: db ok, no jobs (queue not implemented yet)")
