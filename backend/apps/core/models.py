"""System-wide settings kept in the database (operator-editable; docs/04 §Ustawienia)."""

from django.db import models
from django.utils import timezone


class MailSettings(models.Model):
    """Single row (pk=1). Overrides SMTP_URL from the environment when `enabled`."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    host = models.TextField(blank=True, default="")
    port = models.PositiveIntegerField(default=587)
    username = models.TextField(blank=True, default="")
    password_enc = models.BinaryField(null=True, blank=True)  # AES-GCM, scope "mail"
    use_tls = models.BooleanField(default=True)  # STARTTLS
    use_ssl = models.BooleanField(default=False)  # implicit TLS (465)
    from_email = models.TextField(blank=True, default="")
    timeout_s = models.PositiveIntegerField(default=15)
    updated_at = models.DateTimeField(default=timezone.now)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mail_settings"

    def __str__(self) -> str:
        return f"SMTP {self.host}:{self.port}" if self.enabled else "SMTP (env)"

    @classmethod
    def load(cls) -> "MailSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row
