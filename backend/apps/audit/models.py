"""Append-only audit log (docs/03). The app DB role has no UPDATE/DELETE on this table."""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    # ON DELETE SET NULL is enforced by the database (migration 0002): the app role may not
    # UPDATE the append-only audit_log, but referential-integrity triggers run as the owner.
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    action = models.TextField()  # e.g. auth.login, auth.totp.enabled, device.mode.changed
    target_type = models.TextField(blank=True, default="")
    target_id = models.UUIDField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["tenant", "ts"], name="audit_log_tenant_ts"),
            models.Index(fields=["user", "ts"], name="audit_log_user_ts"),
            models.Index(fields=["action", "ts"], name="audit_log_action_ts"),
        ]

    def __str__(self) -> str:
        return f"{self.ts:%Y-%m-%d %H:%M:%S} {self.action}"
