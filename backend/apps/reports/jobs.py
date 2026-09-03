"""render_report job, schedule runner and file retention (docs/10 §Harmonogram)."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.ingest import queue
from apps.ingest.models import Job
from apps.ingest.queue import job_handler

from . import render, services
from .models import FileStatus, ReportFile, ReportFormat, ReportSchedule

log = logging.getLogger("termolink.reports")
FILE_TTL = timedelta(days=30)


def request_file(
    *,
    tenant: Any,
    report_type: str,
    params: dict[str, Any],
    fmt: str,
    requested_by: Any | None = None,
    schedule: ReportSchedule | None = None,
) -> tuple[ReportFile, Job]:
    file = ReportFile.objects.create(
        tenant=tenant,
        schedule=schedule,
        requested_by=requested_by,
        report_type=report_type,
        params=params,
        format=fmt,
        expires_at=timezone.now() + FILE_TTL,
    )
    job = queue.enqueue(
        "render_report",
        {"report_file_id": str(file.id)},
        tenant=tenant,
        created_by=requested_by,
        priority=50,
        max_attempts=2,
    )
    return file, job


@job_handler("render_report")
def render_report(job: Job) -> dict[str, Any]:
    file = ReportFile.objects.select_related("tenant", "schedule").get(
        id=job.payload["report_file_id"]
    )
    try:
        params = services.parse_params(file.tenant, file.params)
        data = services.build(file.tenant, params)
        if file.format == ReportFormat.CSV:
            content = render.render_csv(data).encode("utf-8")
        else:
            content = render.render_pdf(render.render_html(data, file.tenant))
        rel = Path("reports") / str(file.tenant_id) / f"{file.id}.{file.format}"
        target = Path(settings.MEDIA_ROOT) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        file.file_path = str(rel).replace("\\", "/")
        file.size_bytes = len(content)
        file.status = FileStatus.DONE
        file.finished_at = timezone.now()
        file.save(update_fields=["file_path", "size_bytes", "status", "finished_at"])
    except Exception as exc:  # noqa: BLE001 — recorded on the file, job does not retry blindly
        log.exception("report %s failed", file.id)
        file.status = FileStatus.FAILED
        file.error = str(exc)[:500]
        file.finished_at = timezone.now()
        file.save(update_fields=["status", "error", "finished_at"])
        return {"status": "failed", "error": file.error}
    if file.schedule and file.schedule.recipients:
        _mail_schedule(file)
    return {"status": "done", "bytes": file.size_bytes}


def _mail_schedule(file: ReportFile) -> None:
    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/t/{file.tenant_id}/reports"
    schedule = file.schedule
    assert schedule is not None
    try:
        send_mail(
            subject=f"Termolink — raport „{schedule.name}” jest gotowy",
            message=(
                f"Raport „{schedule.name}” ({file.report_type}, {file.format.upper()}) "
                "został wygenerowany.\n\n"
                f"Pobierz po zalogowaniu: {link}\n\n"
                f"Plik będzie dostępny do {file.expires_at:%Y-%m-%d}.\n\nTermolink · Wodmiar"
            ),
            from_email=None,
            recipient_list=list(schedule.recipients),
        )
    except Exception:  # noqa: BLE001
        log.exception("report mail failed for %s", file.id)


def schedule_reports(now: datetime | None = None) -> int:
    """Worker tick: create jobs for schedules whose cron fired since last_run_at (tenant tz)."""
    now = now or timezone.now()
    created = 0
    for schedule in ReportSchedule.objects.filter(enabled=True).select_related("tenant"):
        zone = ZoneInfo(schedule.tenant.timezone)
        base = (schedule.last_run_at or schedule.created_at).astimezone(zone)
        try:
            nxt = croniter(schedule.cron, base).get_next(datetime)
        except (ValueError, KeyError):
            log.warning("schedule %s has an invalid cron %r", schedule.id, schedule.cron)
            continue
        if nxt > now.astimezone(zone):
            continue
        start, end = services.period_range(schedule.period, schedule.tenant.timezone, now)
        params = {
            "report_type": schedule.report_type,
            "device_ids": [str(d) for d in schedule.device_ids],
            "from": start.isoformat(),
            "to": end.isoformat(),
            "resolution": schedule.resolution,
            "features": list(schedule.features),
        }
        request_file(
            tenant=schedule.tenant,
            report_type=schedule.report_type,
            params=params,
            fmt=schedule.format,
            requested_by=schedule.created_by,
            schedule=schedule,
        )
        schedule.last_run_at = now
        schedule.save(update_fields=["last_run_at"])
        created += 1
    return created


def purge_expired(now: datetime | None = None) -> int:
    now = now or timezone.now()
    n = 0
    for file in ReportFile.objects.filter(expires_at__lt=now):
        if file.file_path:
            path = Path(settings.MEDIA_ROOT) / file.file_path
            if path.exists():
                path.unlink()
        file.delete()
        n += 1
    return n
