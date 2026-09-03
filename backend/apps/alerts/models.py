"""Alerts and alert rules (docs/03 §Alarmy, docs/10 §Alarmy)."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AlertType(models.TextChoices):
    DEVICE_OFFLINE = "device_offline", "Urządzenie offline"
    VALUE_OUT_OF_RANGE = "value_out_of_range", "Wartość poza zakresem"
    DEVICE_MESSAGE = "device_message", "Komunikat urządzenia"
    PROVIDER_ACCOUNT = "provider_account", "Konto producenta"
    VERIFY_MISMATCH = "verify_mismatch", "Komenda niepotwierdzona"
    WORKER_DOWN = "worker_down", "Brak workera"


class Severity(models.TextChoices):
    INFO = "info", "informacja"
    WARNING = "warning", "ostrzeżenie"
    CRITICAL = "critical", "krytyczny"


# rule types a tenant may configure (the rest are always-on, operator-facing)
CONFIGURABLE_TYPES = (
    AlertType.DEVICE_OFFLINE,
    AlertType.VALUE_OUT_OF_RANGE,
    AlertType.DEVICE_MESSAGE,
)
OPERATOR_TYPES = (AlertType.PROVIDER_ACCOUNT, AlertType.VERIFY_MISMATCH, AlertType.WORKER_DOWN)
DEFAULT_OFFLINE_MINUTES = 30


class AlertRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="alert_rules"
    )
    device = models.ForeignKey(
        "devices.Device",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="alert_rules",
    )
    type = models.TextField(choices=AlertType.choices)
    # device_offline: {minutes, email}; value_out_of_range: {feature, property, min, max, email};
    # device_message: {email}
    config = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "alert_rules"
        ordering = ["type", "created_at"]

    def __str__(self) -> str:
        return f"{self.type} ({self.device_id or 'tenant'})"

    @property
    def email_enabled(self) -> bool:
        return bool(self.config.get("email", True))


class Alert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="alerts"
    )
    device = models.ForeignKey(
        "devices.Device", null=True, blank=True, on_delete=models.CASCADE, related_name="alerts"
    )
    rule = models.ForeignKey(
        AlertRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    type = models.TextField(choices=AlertType.choices)
    severity = models.TextField(choices=Severity.choices, default=Severity.WARNING)
    key = models.TextField(default="")  # dedup key within (tenant, device, type)
    message = models.TextField()
    details = models.JSONField(default=dict)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alerts"
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["tenant", "closed_at", "-opened_at"], name="alerts_tenant_open"),
            models.Index(fields=["device", "type", "key"], name="alerts_dedup"),
        ]

    def __str__(self) -> str:
        return f"{self.type}: {self.message[:60]}"

    @property
    def is_open(self) -> bool:
        return self.closed_at is None
