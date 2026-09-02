"""Provider account services: OAuth connect, token freshness, discover (docs/02 §A, docs/06)."""

import secrets
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.adapters.base import AuthError, ProviderTokens, RateLimitedError, TransientError
from apps.adapters.registry import get_adapter
from apps.audit.services import audit
from apps.core.exceptions import ApiError
from apps.ingest import queue
from apps.ingest.models import Job
from apps.tenants.context import system_context
from apps.tenants.models import Tenant

from . import budget
from .crypto import load_tokens, store_tokens, token_fields
from .models import AccountStatus, ApiCall, CallKind, OAuthState, ProviderAccount

OAUTH_STATE_TTL = timedelta(minutes=15)
ACCESS_TOKEN_SAFETY_S = 60  # refresh proactively 60 s before expiry (docs/01 §2)


def redirect_uri(provider: str) -> str:
    return f"{settings.OAUTH_REDIRECT_BASE.rstrip('/')}/oauth/{provider}/callback"


# --- connect ---------------------------------------------------------------------------------


def start_authorization(
    request: HttpRequest, *, actor: Any, tenant: Tenant, provider: str, label: str = ""
) -> str:
    adapter = get_adapter(provider)
    if not getattr(settings, f"{provider.upper()}_CLIENT_ID", ""):
        raise ApiError(
            "provider_not_configured",
            f"Brak {provider.upper()}_CLIENT_ID w konfiguracji.",
            status_code=503,
        )
    state = secrets.token_urlsafe(32)
    start = adapter.auth_start(redirect_uri(provider), state)
    OAuthState.objects.create(
        state=state,
        code_verifier=str(start.saved.get("code_verifier", "")),
        tenant=tenant,
        user=actor,
        provider=provider,
        redirect_uri=redirect_uri(provider),
        label=label,
        expires_at=timezone.now() + OAUTH_STATE_TTL,
    )
    audit(
        "provider.auth.started",
        request=request,
        user=actor,
        tenant=tenant,
        details={"provider": provider},
    )
    return start.url


def finish_authorization(
    request: HttpRequest, *, provider: str, params: dict[str, Any]
) -> tuple[Tenant, ProviderAccount | None, str | None]:
    """Callback: validate state, exchange the code, store tokens, enqueue discover.

    Runs in the `system` context (the callback arrives without a tenant session). Returns
    (tenant, account, error_code).
    """
    state_value = str(params.get("state", ""))
    with system_context():
        pending = OAuthState.objects.filter(state=state_value, provider=provider).first()
        if pending is None or not pending.is_valid:
            raise ApiError("invalid_state", "Nieprawidłowy lub wygasły state.", status_code=400)
        tenant = pending.tenant
        pending.delete()
        if "code" not in params:
            audit(
                "provider.auth.failed",
                tenant=tenant,
                details={"provider": provider, "error": str(params.get("error"))},
            )
            return tenant, None, str(params.get("error") or "access_denied")
        adapter = get_adapter(provider)
        try:
            tokens = async_to_sync(adapter.auth_finish)(
                pending.redirect_uri, params, {"code_verifier": pending.code_verifier}
            )
        except AuthError as exc:
            audit(
                "provider.auth.failed",
                tenant=tenant,
                details={"provider": provider, "error": str(exc)[:200]},
            )
            return tenant, None, "token_exchange_failed"
        except TransientError as exc:
            audit(
                "provider.auth.failed",
                tenant=tenant,
                details={"provider": provider, "error": str(exc)[:200]},
            )
            return tenant, None, "provider_unavailable"

        account = (
            ProviderAccount.objects.filter(
                tenant=tenant, provider=provider, external_user_id=tokens.external_user_id
            ).first()
            if tokens.external_user_id
            else None
        )
        if account is None:
            account = ProviderAccount(tenant=tenant, provider=provider, label=pending.label)
            budget_defaults = adapter.default_budget
            account.budget_limit = budget_defaults.limit
            account.budget_window_s = budget_defaults.window_s
            account.short_limit = budget_defaults.short_limit or 0
            account.short_window_s = budget_defaults.short_window_s or 0
        store_tokens(account, tokens)
        account.set_status(AccountStatus.ACTIVE)
        account.save()
        audit(
            "provider.account.connected",
            request=request,
            user=pending.user,
            tenant=tenant,
            target=account,
            details={"provider": provider},
        )
        job = queue.enqueue("discover", {"account_id": str(account.id)}, tenant=tenant, priority=20)
    return tenant, account, None if job else None


# --- tokens ----------------------------------------------------------------------------------


def ensure_fresh_tokens(account: ProviderAccount) -> ProviderTokens:
    """Return usable tokens, refreshing (from the reserve budget) when close to expiry."""
    tokens = load_tokens(account)
    if (
        tokens.access_token
        and tokens.access_expires_at
        and tokens.access_expires_at - time.time() > ACCESS_TOKEN_SAFETY_S
    ):
        return tokens
    return refresh_tokens(account, tokens)


def refresh_tokens(
    account: ProviderAccount, tokens: ProviderTokens | None = None
) -> ProviderTokens:
    tokens = tokens or load_tokens(account)
    call = budget.try_acquire(account.id, CallKind.REFRESH_TOKEN)
    if call is None:
        raise RateLimitedError("no reserve budget for token refresh")
    adapter = get_adapter(account.provider)
    started = time.monotonic()
    try:
        fresh = async_to_sync(adapter.refresh)(tokens)
    except AuthError as exc:
        budget.finish_call(call, http_status=401, duration_ms=_ms(started), error_type="auth")
        mark_reauth_required(account, str(exc)[:200])
        raise
    except TransientError as exc:
        budget.finish_call(call, http_status=None, duration_ms=_ms(started), error_type="transient")
        raise TransientError(str(exc)) from exc
    budget.finish_call(call, http_status=200, duration_ms=_ms(started))
    store_tokens(account, fresh)
    account.save(update_fields=[*token_fields(), "updated_at"])
    return fresh


def mark_reauth_required(account: ProviderAccount, reason: str) -> None:
    account.set_status(AccountStatus.REAUTH_REQUIRED, reason)
    account.save(
        update_fields=["status", "status_reason", "status_since", "status_until", "updated_at"]
    )
    audit(
        "provider.account.reauth_required",
        tenant=account.tenant,
        target=account,
        details={"reason": reason},
    )


def mark_rate_limited(account: ProviderAccount, retry_after_s: int | None) -> None:
    until = timezone.now() + timedelta(seconds=retry_after_s or 3600)
    account.set_status(AccountStatus.RATE_LIMITED, "provider rate limit", until)
    account.save(
        update_fields=["status", "status_reason", "status_since", "status_until", "updated_at"]
    )
    audit(
        "provider.account.rate_limited",
        tenant=account.tenant,
        target=account,
        details={"until": until.isoformat()},
    )


def reactivate_if_due(account: ProviderAccount) -> None:
    if (
        account.status == AccountStatus.RATE_LIMITED
        and account.status_until
        and account.status_until <= timezone.now()
    ):
        account.set_status(AccountStatus.ACTIVE)
        account.save(
            update_fields=["status", "status_reason", "status_since", "status_until", "updated_at"]
        )


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# --- discover --------------------------------------------------------------------------------


def run_discover(account: ProviderAccount) -> int:
    """One `discover` API call → upsert discovered_devices. Returns the number of devices."""
    from apps.devices.models import DiscoveredDevice

    reactivate_if_due(account)
    if account.status != AccountStatus.ACTIVE:
        raise ApiError("account_inactive", f"Konto ma status {account.status}.", status_code=409)
    tokens = ensure_fresh_tokens(account)
    call = budget.try_acquire(account.id, CallKind.DISCOVER)
    if call is None:
        raise RateLimitedError("no reserve budget for discover")
    adapter = get_adapter(account.provider)
    started = time.monotonic()
    try:
        devices = async_to_sync(adapter.discover)(tokens)
    except AuthError as exc:
        budget.finish_call(call, http_status=401, duration_ms=_ms(started), error_type="auth")
        mark_reauth_required(account, str(exc)[:200])
        raise
    except RateLimitedError as exc:
        budget.finish_call(
            call, http_status=429, duration_ms=_ms(started), error_type="rate_limited"
        )
        mark_rate_limited(account, exc.retry_after_s)
        raise
    except Exception as exc:
        budget.finish_call(
            call, http_status=None, duration_ms=_ms(started), error_type=type(exc).__name__
        )
        raise
    budget.finish_call(call, http_status=200, duration_ms=_ms(started))
    now = timezone.now()
    with transaction.atomic():
        for d in devices:
            DiscoveredDevice.objects.update_or_create(
                provider_account=account,
                installation_id=d.external_ids["installationId"],
                gateway_serial=d.external_ids["gatewaySerial"],
                device_id=d.external_ids["deviceId"],
                defaults={
                    "tenant": account.tenant,
                    "model": d.model,
                    "device_type": d.device_type,
                    "online": d.online,
                    "raw": d.raw,
                    "seen_at": now,
                },
            )
    return len(devices)


def enqueue_discover(request: HttpRequest, *, actor: Any, account: ProviderAccount) -> Job:
    if budget.available_for_reserve(account) < 1:
        raise ApiError(
            "budget_reserve_exhausted",
            "Rezerwa budżetu API wyczerpana.",
            status_code=429,
            extra={"retry_at": budget.status(account).reset_at},
        )
    audit(
        "provider.discover.requested",
        request=request,
        user=actor,
        tenant=account.tenant,
        target=account,
    )
    return queue.enqueue(
        "discover",
        {"account_id": str(account.id)},
        tenant=account.tenant,
        created_by=actor,
        priority=20,
    )


# --- management ------------------------------------------------------------------------------


def update_account(
    request: HttpRequest, *, actor: Any, account: ProviderAccount, **fields: Any
) -> ProviderAccount:
    allowed = {"label", "budget_limit", "budget_reserve_pct"}
    changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
    for key, value in changes.items():
        setattr(account, key, value)
    if fields.get("status") == AccountStatus.DISABLED:
        account.set_status(AccountStatus.DISABLED, "disabled by operator")
        changes["status"] = AccountStatus.DISABLED
    if changes:
        account.save()
        audit(
            "provider.account.updated",
            request=request,
            user=actor,
            tenant=account.tenant,
            target=account,
            details={"fields": sorted(changes)},
        )
    return account


def disconnect_account(request: HttpRequest, *, actor: Any, account: ProviderAccount) -> int:
    """Disconnect: devices → archived, tokens wiped, account disabled (docs/04)."""
    from apps.devices.models import Device

    now = timezone.now()
    archived = Device.objects.filter(provider_account=account, archived_at__isnull=True).update(
        archived_at=now, updated_at=now
    )
    account.refresh_token_enc = b""
    account.access_token_enc = None
    account.access_expires_at = None
    account.set_status(AccountStatus.DISABLED, "disconnected")
    account.save()
    audit(
        "provider.account.disconnected",
        request=request,
        user=actor,
        tenant=account.tenant,
        target=account,
        details={"devices_archived": archived},
    )
    return archived


def account_payload(account: ProviderAccount) -> dict[str, Any]:
    s = budget.status(account)
    recent_errors = list(
        ApiCall.objects.filter(provider_account=account, error_type__isnull=False)
        .order_by("-ts")
        .values("ts", "kind", "http_status", "error_type")[:5]
    )
    return {
        "id": str(account.id),
        "provider": account.provider,
        "label": account.label,
        "external_user_id": account.external_user_id,
        "status": account.status,
        "status_reason": account.status_reason,
        "status_since": account.status_since,
        "status_until": account.status_until,
        "budget": s.as_dict(),
        "budget_reserve_pct": account.budget_reserve_pct,
        "budget_overcommitted": account.budget_overcommitted,
        "devices_count": account.devices.filter(archived_at__isnull=True).count()
        if hasattr(account, "devices")
        else 0,
        "recent_errors": recent_errors,
        "created_at": account.created_at,
    }


def get_account_or_404(tenant: Tenant, account_id: str | UUID) -> ProviderAccount:
    try:
        return ProviderAccount.objects.get(id=UUID(str(account_id)), tenant=tenant)
    except (ProviderAccount.DoesNotExist, ValueError) as exc:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404) from exc
