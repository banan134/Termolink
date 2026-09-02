"""The worker runs as the RLS-restricted app role in production — exercise that path."""

import pytest
from django.conf import settings
from django.db import connection

from apps.ingest import queue
from apps.ingest.models import Job, JobStatus, WorkerHeartbeat
from apps.ingest.worker import Worker
from apps.tenants.models import Tenant


@pytest.mark.django_db(transaction=True)
def test_full_cycle_as_app_role() -> None:
    tenant = Tenant.objects.create(name="A")
    ok = queue.enqueue("noop", {"x": 1}, tenant=tenant)
    bad = queue.enqueue("fail", max_attempts=1)
    with connection.cursor() as cursor:
        cursor.execute(f'SET ROLE "{settings.DB_APP_USER}"')
    try:
        worker = Worker(concurrency=4)
        assert worker.run_once() == 2
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    ok.refresh_from_db()
    bad.refresh_from_db()
    assert ok.status == JobStatus.DONE and ok.result == {"echo": {"x": 1}}
    assert bad.status == JobStatus.FAILED
    assert WorkerHeartbeat.objects.filter(worker_id=worker.worker_id).exists()
    assert Job.objects.filter(status=JobStatus.RUNNING).count() == 0
