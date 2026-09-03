"""Report schedules and generated files (docs/03 §Alarmy, raporty; docs/10)."""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


class ReportType(models.TextChoices):
    OPERATION = "operation", "Praca urządzenia"
    ENERGY = "energy", "Energia"
    AVAILABILITY = "availability", "Dostępność"
    CHANGES = "changes", "Zmiany"


class ReportFormat(models.TextChoices):
    PDF = "pdf", "PDF"
    CSV = "csv", "CSV"


class FileStatus(models.TextChoices):
    PENDING = "pending", "w przygotowaniu"
    DONE = "done", "gotowy"
    FAILED = "failed", "błąd"


class Period(models.TextChoices):
    LAST_DAY = "last_day", "poprzedni dzień"
    LAST_WEEK = "last_week", "poprzedni tydzień"
    LAST_MONTH = "last_month", "poprzedni miesiąc"


class ReportSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="report_schedules"
    )
    name = models.TextField()
    report_type = models.TextField(choices=ReportType.choices)
    device_ids = ArrayField(models.UUIDField(), default=list)
    features = ArrayField(models.TextField(), default=list, blank=True)
    period = models.TextField(choices=Period.choices, default=Period.LAST_MONTH)
    resolution = models.TextField(default="auto")
    format = models.TextField(choices=ReportFormat.choices, default=ReportFormat.PDF)
    recipients = ArrayField(models.EmailField(), default=list, blank=True)
    cron = models.TextField(default="0 6 1 * *")  # tenant timezone
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "report_schedules"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ReportFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="report_files"
    )
    schedule = models.ForeignKey(
        ReportSchedule, null=True, blank=True, on_delete=models.SET_NULL, related_name="files"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    report_type = models.TextField(choices=ReportType.choices)
    params = models.JSONField(default=dict)
    format = models.TextField(choices=ReportFormat.choices)
    status = models.TextField(choices=FileStatus.choices, default=FileStatus.PENDING)
    error = models.TextField(null=True, blank=True)  # noqa: DJ001
    file_path = models.TextField(null=True, blank=True)  # noqa: DJ001 — relative to MEDIA_ROOT
    size_bytes = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "report_files"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.report_type}.{self.format} [{self.status}]"

    @property
    def filename(self) -> str:
        return f"termolink-{self.report_type}-{self.created_at:%Y%m%d-%H%M}.{self.format}"
