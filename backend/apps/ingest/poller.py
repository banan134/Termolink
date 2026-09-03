"""Scheduler + poller (docs/06). The scheduler runs every worker tick; polls are jobs."""

import logging
import time
from datetime import timedelta
from typing import Any

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.adapters.base import (
    AdapterError,
    AuthError,
    DeviceDescriptor,
    DeviceOfflineError,
    RateLimitedError,
    TransientError,
)
from apps.adapters.registry import get_adapter
from apps.devices.models import Device, DeviceStatus
from apps.providers import budget
from apps.providers.models import AccountStatus, CallKind, ProviderAccount
from apps.providers.services import (
    ensure_fresh_tokens,
    mark_rate_limited,
    mark_reauth_required,
    reactivate_if_due,
)

from . import queue, status
from .models import Job, JobStatus
from .services import ingest

log = logging.getLogger("termolink.worker")


def descriptor_for(device: Device) -> DeviceDescriptor:
    return DeviceDescriptor(
        external_ids=dict(device.external_ids),
        model=device.model or None,
        serial=device.serial,
        device_type=None,
        online=None,
        raw={},
    )


# --- scheduler --------------------------------------------------------------------------------


def schedule_polls(now: Any | None = None) -> int:
    """Enqueue `poll` jobs for due devices within each account's budget (docs/06 §Scheduler)."""
    now = now or timezone.now()
    enqueued = 0
    for account in ProviderAccount.objects.exclude(status=AccountStatus.DISABLED):
        reactivate_if_due(account)
        if account.status != AccountStatus.ACTIVE:
            continue
        devices = list(
            Device.objects.filter(provider_account=account, archived_at__isnull=True).order_by(
                "next_poll_at"
            )
        )
        n = len(devices)
        if n == 0:
            continue
        available = budget.available_for_poll(account)
        manual = [d.poll_interval_s for d in devices if d.poll_interval_s]
        overcommitted = (
            bool(manual)
            and sum(
                account.budget_window_s / max(i, 60)
                for i in [d.poll_interval_s or budget.auto_interval_s(account, n) for d in devices]
            )
            > account.poll_budget
        )
        if overcommitted != account.budget_overcommitted:
            account.budget_overcommitted = overcommitted
            account.save(update_fields=["budget_overcommitted", "updated_at"])
        pending = set(
            Job.objects.filter(kind="poll", status__in=[JobStatus.QUEUED, JobStatus.RUNNING])
            .filter(payload__device_id__in=[str(d.id) for d in devices])
            .values_list("payload__device_id", flat=True)
        )
        floor = dev_poll_interval() or 0
        for device in devices:
            interval = max(budget.interval_for(account, n, device.poll_interval_s), floor)
            if overcommitted and device.poll_interval_s:
                interval = max(interval, budget.auto_interval_s(account, n))
            status.check_stale(device, interval, now)
            if device.next_poll_at > now or str(device.id) in pending:
                continue
            if available <= 0:
                break
            queue.enqueue(
                "poll",
                {"device_id": str(device.id)},
                tenant=device.tenant,
                provider_account_id=account.id,
                priority=100,
            )
            device.next_poll_at = now + timedelta(seconds=interval)
            device.save(update_fields=["next_poll_at", "updated_at"])
            available -= 1
            enqueued += 1
    return enqueued


# --- poller -----------------------------------------------------------------------------------


def poll_device(device: Device, *, kind: str = CallKind.POLL) -> dict[str, Any]:
    """One read of all features (docs/06 §Poller). Raises TransientError to let the job retry."""
    account = device.provider_account
    reactivate_if_due(account)
    if account.status != AccountStatus.ACTIVE:
        status.set_status(
            device,
            DeviceStatus.RATE_LIMITED
            if account.status == AccountStatus.RATE_LIMITED
            else device.status,
            account.status,
        )
        return {"skipped": account.status}

    call = budget.try_acquire(account.id, kind, device_id=device.id)
    if call is None:
        raise TransientError("budget exhausted; retry later")
    started = time.monotonic()
    try:
        tokens = ensure_fresh_tokens(account)
        adapter = get_adapter(device.provider)
        features = async_to_sync(adapter.read_features)(tokens, descriptor_for(device))
    except DeviceOfflineError as exc:
        budget.finish_call(call, http_status=None, duration_ms=_ms(started), error_type="offline")
        status.mark_offline(device, str(exc)[:200])
        _touch_polled(device)
        return {"status": "offline"}
    except AuthError as exc:
        budget.finish_call(call, http_status=401, duration_ms=_ms(started), error_type="auth")
        mark_reauth_required(account, str(exc)[:200])
        return {"status": "reauth_required"}
    except RateLimitedError as exc:
        budget.finish_call(
            call, http_status=429, duration_ms=_ms(started), error_type="rate_limited"
        )
        mark_rate_limited(account, exc.retry_after_s)
        status.mark_rate_limited(device)
        return {"status": "rate_limited"}
    except TransientError as exc:
        budget.finish_call(call, http_status=None, duration_ms=_ms(started), error_type="transient")
        status.record_error(device, str(exc)[:200])
        raise
    except AdapterError as exc:
        budget.finish_call(
            call, http_status=None, duration_ms=_ms(started), error_type=type(exc).__name__
        )
        status.record_error(device, str(exc)[:200])
        if getattr(exc, "api_changed", False):
            log.error("possible API change for device %s: %s", device.id, exc)
        return {"status": "error", "error": str(exc)[:200]}
    budget.finish_call(call, http_status=200, duration_ms=_ms(started))
    with transaction.atomic():
        stats = ingest(device, features)
        status.mark_online(device)
        _touch_polled(device)
    from apps.control.services import settle_pending_after_poll

    settle_pending_after_poll(device)
    return {"status": "online", "features": len(features), "history_rows": stats.history_rows}


def _touch_polled(device: Device) -> None:
    device.last_polled_at = timezone.now()
    device.save(update_fields=["last_polled_at", "updated_at"])


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def dev_poll_interval() -> int | None:
    """docs/15: DEV_POLL_INTERVAL_S protects the shared budget in dev (unset in prod)."""
    value = getattr(settings, "DEV_POLL_INTERVAL_S", None)
    return int(value) if value else None
