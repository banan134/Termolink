"""Queue semantics: ordering, SKIP LOCKED, retries/backoff, stale release, worker tick."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.ingest import queue
from apps.ingest.models import Job, JobStatus, WorkerHeartbeat
from apps.ingest.worker import Worker
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.mark.django_db
def test_claim_orders_by_priority_then_run_at() -> None:
    later = queue.enqueue("noop", {"n": "later"}, run_at=timezone.now() + timedelta(hours=1))
    low = queue.enqueue("noop", {"n": "low"}, priority=200)
    high = queue.enqueue("noop", {"n": "high"}, priority=10)
    assert queue.claim("w1").id == high.id  # type: ignore[union-attr]
    assert queue.claim("w1").id == low.id  # type: ignore[union-attr]
    assert queue.claim("w1") is None  # `later` is not due yet
    later.refresh_from_db()
    assert later.status == JobStatus.QUEUED


@pytest.mark.django_db(transaction=True)
def test_two_workers_never_take_the_same_job() -> None:
    a = queue.enqueue("noop", {"n": 1})
    b = queue.enqueue("noop", {"n": 2})
    got: list[int] = []
    # first claim holds its row lock inside an open transaction; second must skip it
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority, run_at, id "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            )
            got.append(cursor.fetchone()[0])
        # a second connection (transactional test) claims concurrently
        from django.db import connections

        other = connections.create_connection("default")
        try:
            with other.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET status='running', locked_by='w2', locked_at=now() "
                    "WHERE id = (SELECT id FROM jobs WHERE status='queued' "
                    "ORDER BY priority, run_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"
                )
                got.append(cursor.fetchone()[0])
            other.commit()
        finally:
            other.close()
    assert set(got) == {a.id, b.id}


@pytest.mark.django_db
def test_failure_retries_with_backoff_then_fails() -> None:
    job = queue.enqueue("fail", {"message": "boom"}, max_attempts=2)
    worker = Worker(concurrency=4)
    assert worker.run_once() == 1
    job.refresh_from_db()
    assert job.status == JobStatus.QUEUED and job.attempts == 1
    assert "boom" in (job.last_error or "")
    assert timedelta(seconds=50) < job.run_at - timezone.now() <= timedelta(minutes=1)

    Job.objects.filter(id=job.id).update(run_at=timezone.now())
    assert worker.run_once() == 1
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED and job.attempts == 2 and job.finished_at


@pytest.mark.django_db
def test_stale_locks_are_released() -> None:
    job = queue.enqueue("noop")
    Job.objects.filter(id=job.id).update(
        status=JobStatus.RUNNING, locked_by="dead", locked_at=timezone.now() - timedelta(minutes=11)
    )
    assert queue.release_stale() == 1
    job.refresh_from_db()
    assert job.status == JobStatus.QUEUED and job.locked_by is None


@pytest.mark.django_db
def test_unknown_kind_fails_immediately() -> None:
    job = queue.enqueue("nope")
    Worker().run_once()
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED and "unknown job kind" in (job.last_error or "")


@pytest.mark.django_db
def test_run_worker_once_runs_jobs_and_writes_heartbeat(capsys: pytest.CaptureFixture[str]) -> None:
    tenant = Tenant.objects.create(name="A")
    job = queue.enqueue("noop", {"hello": "world"}, tenant=tenant)
    call_command("run_worker", "--once", "--concurrency", "2")
    assert "1 job(s) run" in capsys.readouterr().out
    job.refresh_from_db()
    assert job.status == JobStatus.DONE and job.result == {"echo": {"hello": "world"}}
    assert job.locked_by is None and job.finished_at is not None
    assert WorkerHeartbeat.objects.count() == 0  # removed on clean shutdown

    worker = Worker(concurrency=1)
    worker.run_once()
    beat = WorkerHeartbeat.objects.get(worker_id=worker.worker_id)
    assert beat.concurrency == 1 and timezone.now() - beat.last_beat_at < timedelta(seconds=5)


@pytest.mark.django_db
def test_purge_finished_keeps_14_days() -> None:
    old = queue.enqueue("noop")
    Job.objects.filter(id=old.id).update(
        status=JobStatus.DONE, finished_at=timezone.now() - timedelta(days=15)
    )
    fresh = queue.enqueue("noop")
    Job.objects.filter(id=fresh.id).update(status=JobStatus.DONE, finished_at=timezone.now())
    assert queue.purge_finished() == 1
    assert Job.objects.filter(id=fresh.id).exists()


@pytest.mark.django_db
def test_job_api_is_tenant_scoped() -> None:
    a, b = Tenant.objects.create(name="A"), Tenant.objects.create(name="B")
    User.objects.create_user("ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=a)
    mine = queue.enqueue("noop", tenant=a)
    theirs = queue.enqueue("noop", tenant=b)
    client = Client()
    client.post(
        "/api/v1/auth/login",
        {"email": "ua@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    ok = client.get(f"/api/v1/jobs/{mine.public_id}")
    assert ok.status_code == 200 and ok.json()["status"] == "queued"
    assert client.get(f"/api/v1/jobs/{theirs.public_id}").status_code == 404
    assert client.get("/api/v1/jobs/not-a-uuid").status_code == 404
    assert Client().get(f"/api/v1/jobs/{mine.public_id}").status_code in (401, 403)
