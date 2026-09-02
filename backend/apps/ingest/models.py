"""DB-backed job queue and worker heartbeats (docs/02 §Kolejka, docs/03, docs/06)."""

import uuid

from django.conf import settings
from django.db import models


class JobStatus(models.TextChoices):
    QUEUED = "queued", "W kolejce"
    RUNNING = "running", "W toku"
    DONE = "done", "Zakończone"
    FAILED = "failed", "Nieudane"


class Job(models.Model):
    id = models.BigAutoField(primary_key=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="jobs"
    )
    provider_account_id = models.UUIDField(null=True, blank=True)  # FK arrives in stage 2
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    run_at = models.DateTimeField(db_index=True)
    priority = models.IntegerField(default=100)  # lower runs first
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.TextField(null=True, blank=True)  # noqa: DJ001 — NULL = not locked
    status = models.TextField(choices=JobStatus.choices, default=JobStatus.QUEUED)
    last_error = models.TextField(null=True, blank=True)  # noqa: DJ001
    result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "jobs"
        indexes = [
            models.Index(fields=["status", "run_at", "priority"], name="jobs_status_run_at_prio"),
        ]

    def __str__(self) -> str:
        return f"job {self.id} {self.kind} [{self.status}]"


class WorkerHeartbeat(models.Model):
    worker_id = models.TextField(primary_key=True)
    hostname = models.TextField(blank=True, default="")
    concurrency = models.IntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    last_beat_at = models.DateTimeField()
    jobs_done = models.BigIntegerField(default=0)
    jobs_failed = models.BigIntegerField(default=0)

    class Meta:
        db_table = "worker_heartbeats"

    def __str__(self) -> str:
        return f"{self.worker_id} @ {self.last_beat_at:%H:%M:%S}"
