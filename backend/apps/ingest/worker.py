"""Worker loop: heartbeat, stale-lock release, claim and run jobs (docs/02, docs/06)."""

import logging
import socket
import time
import uuid

from django.db import connection, transaction
from django.utils import timezone

from apps.tenants.context import SYSTEM, set_context

from . import queue
from .models import WorkerHeartbeat

log = logging.getLogger("termolink.worker")


class Worker:
    def __init__(self, *, concurrency: int = 4, tick: float = 5.0) -> None:
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.concurrency = max(1, concurrency)
        self.tick = tick
        self.done = 0
        self.failed = 0

    def heartbeat(self) -> None:
        WorkerHeartbeat.objects.update_or_create(
            worker_id=self.worker_id,
            defaults={
                "hostname": socket.gethostname(),
                "concurrency": self.concurrency,
                "last_beat_at": timezone.now(),
                "jobs_done": self.done,
                "jobs_failed": self.failed,
            },
        )

    def run_once(self) -> int:
        """One tick: heartbeat, release stale locks, run up to `concurrency` due jobs."""
        with transaction.atomic():
            set_context(SYSTEM)
            self.heartbeat()
            queue.release_stale()
        ran = 0
        while ran < self.concurrency:
            with transaction.atomic():
                set_context(SYSTEM)
                job = queue.claim(self.worker_id)
            if job is None:
                break
            log.info("job %s %s start (attempt %s)", job.id, job.kind, job.attempts)
            if queue.run_job(job):
                self.done += 1
            else:
                self.failed += 1
            ran += 1
        return ran

    def run_forever(self) -> None:
        log.info(
            "worker %s starting (concurrency=%s, tick=%ss)",
            self.worker_id,
            self.concurrency,
            self.tick,
        )
        while True:
            try:
                ran = self.run_once()
            except Exception:  # noqa: BLE001 — keep the loop alive, e.g. DB restart
                log.exception("worker tick failed")
                connection.close()
                ran = 0
            if ran == 0:
                time.sleep(self.tick)

    def shutdown(self) -> None:
        with transaction.atomic():
            set_context(SYSTEM)
            WorkerHeartbeat.objects.filter(worker_id=self.worker_id).delete()
