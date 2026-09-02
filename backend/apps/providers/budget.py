"""API budget per provider account — docs/06-polling-and-budget.md.

All decisions are made inside a DB transaction holding a row lock on the account, so any number
of workers/web processes can call try_acquire concurrently and never exceed the limit.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .models import POLL_KINDS, RESERVE_KINDS, ApiCall, ProviderAccount

SHORT_WINDOW_SAFETY = 0.9  # never more than 90 % of the short limit (docs/06: 110 of 120)
MIN_INTERVAL_S = 60


@dataclass(frozen=True)
class BudgetStatus:
    limit: int
    window_s: int
    used: int
    poll_budget: int
    poll_used: int
    reserve: int
    reserve_used: int
    short_limit: int
    short_used: int
    reset_at: Any  # earliest moment a slot frees up (oldest call in window + window)

    @property
    def available_for_poll(self) -> int:
        return max(0, min(self.poll_budget - self.poll_used, self.limit - self.used))

    @property
    def available_for_reserve(self) -> int:
        return max(0, min(self.reserve - self.reserve_used, self.limit - self.used))

    def as_dict(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "limit": self.limit,
            "reset_at": self.reset_at,
            "poll_used": self.poll_used,
            "poll_budget": self.poll_budget,
            "reserve_used": self.reserve_used,
            "reserve": self.reserve,
            "short_used": self.short_used,
            "short_limit": self.short_limit,
        }


def _counts(account: ProviderAccount, now: Any) -> tuple[int, int, int, int, Any]:
    window_start = now - timedelta(seconds=account.budget_window_s)
    short_start = now - timedelta(seconds=account.short_window_s)
    rows = list(
        ApiCall.objects.filter(provider_account=account, ts__gt=window_start).values_list(
            "kind", "ts"
        )
    )
    used = len(rows)
    poll_used = sum(1 for kind, _ in rows if kind in POLL_KINDS)
    reserve_used = sum(1 for kind, _ in rows if kind in RESERVE_KINDS)
    short_used = sum(1 for _, ts in rows if ts > short_start)
    oldest = min((ts for _, ts in rows), default=None)
    reset_at = oldest + timedelta(seconds=account.budget_window_s) if oldest else now
    return used, poll_used, reserve_used, short_used, reset_at


def status(account: ProviderAccount, now: Any | None = None) -> BudgetStatus:
    now = now or timezone.now()
    used, poll_used, reserve_used, short_used, reset_at = _counts(account, now)
    return BudgetStatus(
        limit=account.budget_limit,
        window_s=account.budget_window_s,
        used=used,
        poll_budget=account.poll_budget,
        poll_used=poll_used,
        reserve=account.reserve,
        reserve_used=reserve_used,
        short_limit=account.short_limit,
        short_used=short_used,
        reset_at=reset_at,
    )


def used(account: ProviderAccount, window_s: int | None = None) -> int:
    since = timezone.now() - timedelta(seconds=window_s or account.budget_window_s)
    return ApiCall.objects.filter(provider_account=account, ts__gt=since).count()


def available_for_poll(account: ProviderAccount) -> int:
    return status(account).available_for_poll


def available_for_reserve(account: ProviderAccount) -> int:
    return status(account).available_for_reserve


def try_acquire(account_id: UUID, kind: str, *, device_id: UUID | None = None) -> ApiCall | None:
    """Reserve one API call of `kind`; returns the ledger row to complete later, or None.

    The ONLY place that creates api_calls rows before a call (docs/06).
    """
    with transaction.atomic():
        account = ProviderAccount.objects.select_for_update().get(id=account_id)
        now = timezone.now()
        s = status(account, now)
        if s.used >= s.limit:
            return None
        if s.short_used >= int(account.short_limit * SHORT_WINDOW_SAFETY):
            return None
        if kind in POLL_KINDS and s.poll_used >= s.poll_budget:
            return None
        if kind in RESERVE_KINDS and s.reserve_used >= s.reserve:
            return None
        return ApiCall.objects.create(
            provider_account=account, ts=now, kind=kind, device_id=device_id
        )


def finish_call(
    call: ApiCall,
    *,
    http_status: int | None,
    duration_ms: int | None,
    error_type: str | None = None,
) -> None:
    ApiCall.objects.filter(id=call.id).update(
        http_status=http_status, duration_ms=duration_ms, error_type=error_type
    )


# --- polling interval (docs/06 §Interwał odczytu) --------------------------------------------


def auto_interval_s(account: ProviderAccount, active_devices: int) -> int:
    n = max(1, active_devices)
    per_device = account.poll_budget / n  # calls available per device per window
    auto = (
        math.ceil(account.budget_window_s / per_device)
        if per_device > 0
        else account.budget_window_s
    )
    return max(auto, MIN_INTERVAL_S, short_floor_s(account, n))


def short_floor_s(account: ProviderAccount, active_devices: int) -> int:
    if not account.short_limit or not account.short_window_s:
        return 0
    return math.ceil(
        account.short_window_s / (account.short_limit * SHORT_WINDOW_SAFETY) * active_devices
    )


def interval_for(account: ProviderAccount, active_devices: int, device_interval: int | None) -> int:
    auto = auto_interval_s(account, active_devices)
    return max(
        device_interval or auto, MIN_INTERVAL_S, short_floor_s(account, max(1, active_devices))
    )


def purge_old_calls(days: int = 35) -> int:
    """docs/03: api_calls retention 35 days."""
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = ApiCall.objects.filter(ts__lt=cutoff).delete()
    return deleted
