"""Job queue on PostgreSQL (docs/02 §4, docs/06 §Wiele workerów).

Claiming uses `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING`,
so any number of workers can run concurrently without double-processing. Jobs locked for
longer than STALE_AFTER are treated as abandoned (worker died) and released.
If a different queue is ever needed, this module is the only thing to replace.
"""

import logging
import traceback
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from apps.tenants.context import ROLE_SYSTEM, SYSTEM, TenantContext, set_context

from .models import Job, JobStatus

log = logging.getLogger("termolink.worker")

STALE_AFTER = timedelta(minutes=10)
RETRY_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))

Handler = Callable[[Job], dict[str, Any] | None]


def _system_tx() -> Any:
    """Queue bookkeeping runs as `system` in its own transaction.

    Without this, UPDATEs issued in autocommit mode carry no RLS context and silently affect
    0 rows when the worker runs as the restricted app role.
    """
    return _SystemTx()


class _SystemTx:
    def __enter__(self) -> None:
        self._atomic = transaction.atomic()
        self._atomic.__enter__()
        set_context(SYSTEM)

    def __exit__(self, *exc: Any) -> None:
        self._atomic.__exit__(*exc)


HANDLERS: dict[str, Handler] = {}


def job_handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if kind in HANDLERS:
            raise RuntimeError(f"job handler for {kind!r} already registered")
        HANDLERS[kind] = fn
        return fn

    return register


def enqueue(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    tenant: Any | None = None,
    created_by: Any | None = None,
    provider_account_id: Any | None = None,
    run_at: Any | None = None,
    priority: int = 100,
    max_attempts: int = 3,
) -> Job:
    return Job.objects.create(
        kind=kind,
        payload=payload or {},
        tenant=tenant,
        created_by=created_by,
        provider_account_id=provider_account_id,
        run_at=run_at or timezone.now(),
        priority=priority,
        max_attempts=max_attempts,
    )


def claim(worker_id: str) -> Job | None:
    """Atomically take the next due job (lowest priority number, oldest run_at).

    clock_timestamp() rather than now(): now() is frozen at transaction start, which would hide
    jobs enqueued moments ago inside a long-running transaction.
    """
    with _system_tx(), connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE jobs SET status = %s, locked_at = clock_timestamp(), locked_by = %s,
                            attempts = attempts + 1
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = %s AND run_at <= clock_timestamp()
                ORDER BY priority, run_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """,
            [JobStatus.RUNNING, worker_id, JobStatus.QUEUED],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Job.objects.get(id=row[0])


def complete(job: Job, result: dict[str, Any] | None) -> None:
    with _system_tx():
        Job.objects.filter(id=job.id).update(
            status=JobStatus.DONE,
            result=result,
            finished_at=timezone.now(),
            locked_at=None,
            locked_by=None,
        )


def fail(job: Job, error: str, *, final: bool = False) -> None:
    """Retry with backoff (1, 5, 15 min) until max_attempts, then mark failed."""
    if not final and job.attempts < job.max_attempts:
        delay = RETRY_BACKOFF[min(job.attempts - 1, len(RETRY_BACKOFF) - 1)]
        with _system_tx():
            Job.objects.filter(id=job.id).update(
                status=JobStatus.QUEUED,
                run_at=timezone.now() + delay,
                last_error=error[:4000],
                locked_at=None,
                locked_by=None,
            )
    else:
        with _system_tx():
            Job.objects.filter(id=job.id).update(
                status=JobStatus.FAILED,
                last_error=error[:4000],
                finished_at=timezone.now(),
                locked_at=None,
                locked_by=None,
            )


def release_stale(now: Any | None = None) -> int:
    cutoff = (now or timezone.now()) - STALE_AFTER
    with _system_tx():
        released = Job.objects.filter(status=JobStatus.RUNNING, locked_at__lt=cutoff).update(
            status=JobStatus.QUEUED,
            locked_at=None,
            locked_by=None,
            last_error="released: stale lock",
        )
    if released:
        log.warning("released %s stale job(s)", released)
    return released


def run_job(job: Job) -> bool:
    """Execute one claimed job in its own transaction with an explicit RLS context."""
    handler = HANDLERS.get(job.kind)
    if handler is None:
        fail(job, f"unknown job kind {job.kind!r}", final=True)
        return False
    try:
        with transaction.atomic():
            # The worker is trusted code: system role, scoped to the job's tenant for the record.
            set_context(TenantContext(role=ROLE_SYSTEM, tenant_id=job.tenant_id))
            result = handler(job)
    except Exception:  # noqa: BLE001 — any handler failure is recorded on the job
        error = traceback.format_exc()
        log.exception("job %s (%s) failed", job.id, job.kind)
        fail(job, error)
        return False
    complete(job, result)
    return True


def purge_finished(older_than: timedelta = timedelta(days=14)) -> int:
    """docs/03: finished jobs are kept 14 days."""
    cutoff = timezone.now() - older_than
    with _system_tx():
        deleted, _ = Job.objects.filter(
            status__in=[JobStatus.DONE, JobStatus.FAILED], finished_at__lt=cutoff
        ).delete()
    return deleted
