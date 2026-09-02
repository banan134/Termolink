"""Provider accounts, API call ledger and OAuth states — docs/03 §Producenci i konta."""

import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountStatus(models.TextChoices):
    ACTIVE = "active", "Aktywne"
    REAUTH_REQUIRED = "reauth_required", "Wymaga ponownej autoryzacji"
    RATE_LIMITED = "rate_limited", "Limit API wyczerpany"
    DISABLED = "disabled", "Wyłączone"


class ProviderAccount(models.Model):
    """An authorised customer account at a provider; owner of the API budget (docs/06)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="provider_accounts"
    )
    provider = models.TextField()  # key of apps.adapters.registry.ADAPTERS
    external_user_id = models.TextField(null=True, blank=True)  # noqa: DJ001
    label = models.TextField(blank=True, default="")
    refresh_token_enc = models.BinaryField()
    access_token_enc = models.BinaryField(null=True, blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.TextField(blank=True, default="")
    status = models.TextField(choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    status_reason = models.TextField(null=True, blank=True)  # noqa: DJ001
    status_since = models.DateTimeField(default=timezone.now)
    status_until = models.DateTimeField(null=True, blank=True)  # rate_limited → reset time
    budget_limit = models.IntegerField(default=1450)
    budget_window_s = models.IntegerField(default=86400)
    budget_reserve_pct = models.IntegerField(default=15)
    short_limit = models.IntegerField(default=120)
    short_window_s = models.IntegerField(default=600)
    budget_overcommitted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "provider_accounts"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.provider} · {self.label or self.external_user_id or self.id}"

    # --- derived budget numbers (docs/06) ---
    @property
    def reserve(self) -> int:
        return self.budget_limit * self.budget_reserve_pct // 100

    @property
    def poll_budget(self) -> int:
        return self.budget_limit - self.reserve

    def set_status(self, status: str, reason: str | None = None, until: Any = None) -> None:
        if self.status != status:
            self.status_since = timezone.now()
        self.status = status
        self.status_reason = reason
        self.status_until = until


class CallKind(models.TextChoices):
    POLL = "poll", "poll"
    COMMAND = "command", "command"
    VERIFY = "verify", "verify"
    REFRESH = "refresh", "refresh"  # "Odśwież teraz"
    DISCOVER = "discover", "discover"
    REFRESH_TOKEN = "refresh_token", "refresh_token"


POLL_KINDS = frozenset({CallKind.POLL})
RESERVE_KINDS = frozenset(
    {CallKind.COMMAND, CallKind.VERIFY, CallKind.REFRESH, CallKind.DISCOVER, CallKind.REFRESH_TOKEN}
)


class ApiCall(models.Model):
    """Every provider API call, inserted *before* the call by budget.try_acquire (docs/06)."""

    id = models.BigAutoField(primary_key=True)
    provider_account = models.ForeignKey(
        ProviderAccount, on_delete=models.CASCADE, related_name="api_calls"
    )
    ts = models.DateTimeField(default=timezone.now)
    kind = models.TextField(choices=CallKind.choices)
    device_id = models.UUIDField(null=True, blank=True)
    http_status = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    error_type = models.TextField(null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "api_calls"
        indexes = [
            models.Index(fields=["provider_account", "-ts"], name="api_calls_account_ts"),
            models.Index(fields=["ts"], name="api_calls_ts"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.ts:%H:%M:%S} {self.http_status or '…'}"


class OAuthState(models.Model):
    """Pending OAuth authorisation (state → code_verifier), short-lived (docs/02 §A)."""

    state = models.TextField(primary_key=True)
    code_verifier = models.TextField()
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider = models.TextField()
    redirect_uri = models.TextField()
    label = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "oauth_states"

    def __str__(self) -> str:
        return f"{self.provider} state for tenant {self.tenant_id}"

    @property
    def is_valid(self) -> bool:
        return self.expires_at > timezone.now()
