"""Commands — the audited state machine for device control (docs/03, docs/07)."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class CommandStatus(models.TextChoices):
    DRAFT = "draft", "Szkic"
    CONFIRMED = "confirmed", "Potwierdzona"
    EXECUTING = "executing", "Wykonywana"
    SUCCEEDED = "succeeded", "Wysłana"
    FAILED = "failed", "Nieudana"
    VERIFY_PENDING = "verify_pending", "Oczekuje na weryfikację"
    VERIFIED = "verified", "Zweryfikowana"
    VERIFY_MISMATCH = "verify_mismatch", "Niezgodna z odczytem"
    REJECTED = "rejected", "Odrzucona"
    EXPIRED = "expired", "Wygasła"


TERMINAL = frozenset(
    {
        CommandStatus.FAILED,
        CommandStatus.VERIFIED,
        CommandStatus.VERIFY_MISMATCH,
        CommandStatus.REJECTED,
        CommandStatus.EXPIRED,
    }
)


class Command(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="commands")
    device = models.ForeignKey("devices.Device", on_delete=models.CASCADE, related_name="commands")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="commands"
    )
    acted_as_operator = models.BooleanField(default=False)
    feature_name = models.TextField()
    command_name = models.TextField()
    params = models.JSONField(default=dict)
    value_before = models.JSONField(null=True, blank=True)
    value_after = models.JSONField(null=True, blank=True)
    status = models.TextField(choices=CommandStatus.choices, default=CommandStatus.DRAFT)
    sensitive = models.BooleanField(default=False)
    reauth_verified = models.BooleanField(default=False)
    reject_reason = models.TextField(null=True, blank=True)  # noqa: DJ001
    api_status = models.IntegerField(null=True, blank=True)
    api_response = models.JSONField(null=True, blank=True)
    verify_attempts = models.IntegerField(default=0)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "commands"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["device", "-created_at"], name="commands_device_created"),
            models.Index(fields=["tenant", "-created_at"], name="commands_tenant_created"),
        ]

    def __str__(self) -> str:
        return f"{self.command_name} on {self.feature_name} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL
