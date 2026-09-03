"""Alert evaluation — docs/10 §Alarmy.

One open alert per (tenant, device, type, key); auto-closed when the condition clears.
`evaluate_all()` runs from the worker tick (system context), the hooks from the modules that
observe the event (control verify, ingest status).
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.devices.grouping import group_key
from apps.devices.models import Device, DeviceStatus, FeatureLatest, FeatureValue
from apps.ingest.models import WorkerHeartbeat
from apps.providers.models import AccountStatus, ProviderAccount
from apps.tenants.models import Tenant

from . import emails
from .models import (
    DEFAULT_OFFLINE_MINUTES,
    OPERATOR_TYPES,
    Alert,
    AlertRule,
    AlertType,
    Severity,
)

log = logging.getLogger("termolink.alerts")
WORKER_DOWN_AFTER = timedelta(minutes=2)
STALE_HEARTBEAT_PRUNE = timedelta(hours=1)
BACKUP_MAX_AGE = timedelta(hours=26)
EVALUATE_EVERY = timedelta(seconds=60)
_last_run: datetime | None = None


# --- primitives --------------------------------------------------------------------------------


def open_alert(
    *,
    type: str,
    message: str,
    tenant: Tenant | None,
    device: Device | None = None,
    rule: AlertRule | None = None,
    key: str = "",
    severity: str = Severity.WARNING,
    details: dict[str, Any] | None = None,
    email: bool = True,
    extra_recipients: list[str] | None = None,
) -> tuple[Alert, bool]:
    """Idempotent: returns the existing open alert (created=False) for the same dedup key."""
    existing = Alert.objects.filter(
        tenant=tenant, device=device, type=type, key=key, closed_at__isnull=True
    ).first()
    if existing is not None:
        return existing, False
    alert = Alert.objects.create(
        tenant=tenant,
        device=device,
        rule=rule,
        type=type,
        key=key,
        severity=severity,
        message=message,
        details=details or {},
    )
    if email:
        _notify(alert, extra_recipients or [])
    return alert, True


def close_alerts(
    *, type: str, tenant: Tenant | None, device: Device | None = None, key: str | None = None
) -> int:
    qs = Alert.objects.filter(tenant=tenant, device=device, type=type, closed_at__isnull=True)
    if key is not None:
        qs = qs.filter(key=key)
    return qs.update(closed_at=timezone.now())


def acknowledge(alert: Alert, user: User) -> Alert:
    if alert.acknowledged_at is None:
        alert.acknowledged_by = user
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=["acknowledged_by", "acknowledged_at"])
    return alert


def _recipients(alert: Alert, extra: list[str]) -> list[str]:
    out: list[str] = []
    if alert.tenant_id and alert.type not in OPERATOR_TYPES:
        out += list(
            User.objects.filter(
                tenant_id=alert.tenant_id, role=Role.TENANT_ADMIN, is_active=True
            ).values_list("email", flat=True)
        )
    if alert.type in OPERATOR_TYPES:
        if settings.ALERT_EMAIL_OPERATOR:
            out.append(settings.ALERT_EMAIL_OPERATOR)
    out += extra
    return sorted({e for e in out if e})


def _notify(alert: Alert, extra: list[str]) -> None:
    recipients = _recipients(alert, extra)
    if not recipients:
        return
    try:
        emails.send_alert(alert, recipients)
    except Exception:  # noqa: BLE001 — mail failure must not break the worker
        log.exception("alert e-mail failed for %s", alert.id)
        return
    Alert.objects.filter(id=alert.id).update(notified_at=timezone.now())


# --- evaluation --------------------------------------------------------------------------------


def evaluate_all(now: datetime | None = None, *, force: bool = False) -> dict[str, int]:
    """Runs at most once per minute from the worker tick."""
    global _last_run  # noqa: PLW0603
    now = now or timezone.now()
    if not force and _last_run is not None and now - _last_run < EVALUATE_EVERY:
        return {}
    _last_run = now
    stats = {
        "offline": evaluate_offline(now),
        "range": evaluate_out_of_range(now),
        "messages": evaluate_messages(),
        "accounts": evaluate_provider_accounts(),
        "workers": evaluate_workers(now),
        "backup": evaluate_backup(now),
    }
    return stats


def _rules_for(device: Device, type: str) -> list[AlertRule]:
    """Device-specific rule wins over the tenant-wide one."""
    rules = list(
        AlertRule.objects.filter(tenant_id=device.tenant_id, type=type).filter(
            Q(device=device) | Q(device__isnull=True)
        )
    )
    specific = [r for r in rules if r.device_id == device.id]
    return specific or [r for r in rules if r.device_id is None]


def evaluate_offline(now: datetime) -> int:
    """device_offline: status offline/error ≥ minutes (default 30, on for every device)."""
    opened = 0
    for device in Device.objects.filter(archived_at__isnull=True).select_related("tenant"):
        rules = _rules_for(device, AlertType.DEVICE_OFFLINE)
        rule = rules[0] if rules else None
        if rule is not None and not rule.enabled:
            close_alerts(type=AlertType.DEVICE_OFFLINE, tenant=device.tenant, device=device)
            continue
        minutes = int((rule.config.get("minutes") if rule else None) or DEFAULT_OFFLINE_MINUTES)
        down = device.status in (DeviceStatus.OFFLINE, DeviceStatus.ERROR)
        if down and device.status_since <= now - timedelta(minutes=minutes):
            _, created = open_alert(
                type=AlertType.DEVICE_OFFLINE,
                tenant=device.tenant,
                device=device,
                rule=rule,
                severity=Severity.CRITICAL,
                message=f"{device.display_name}: brak połączenia od {minutes} min"
                + (f" ({device.status_detail})" if device.status_detail else ""),
                details={"status": device.status, "since": device.status_since.isoformat()},
                email=rule.email_enabled if rule else True,
            )
            opened += int(created)
        elif not down:
            close_alerts(type=AlertType.DEVICE_OFFLINE, tenant=device.tenant, device=device)
    return opened


def evaluate_out_of_range(now: datetime) -> int:
    """value_out_of_range: outside [min,max] in ≥ 2 consecutive readings."""
    opened = 0
    rules = AlertRule.objects.filter(type=AlertType.VALUE_OUT_OF_RANGE).select_related(
        "tenant", "device"
    )
    for rule in rules:
        feature, prop = rule.config.get("feature"), rule.config.get("property", "value")
        lo, hi = rule.config.get("min"), rule.config.get("max")
        if not feature:
            continue
        devices = (
            [rule.device]
            if rule.device
            else list(Device.objects.filter(tenant=rule.tenant, archived_at__isnull=True))
        )
        for device in devices:
            key = f"{feature}.{prop}"
            if not rule.enabled:
                close_alerts(
                    type=AlertType.VALUE_OUT_OF_RANGE, tenant=rule.tenant, device=device, key=key
                )
                continue
            last_two: list[float] = [
                v
                for v in (
                    FeatureValue.objects.filter(
                        device=device, feature_name=feature, property_name=prop
                    )
                    .exclude(value_num__isnull=True)
                    .order_by("-ts_polled")
                    .values_list("value_num", flat=True)[:2]
                )
                if v is not None
            ]
            if len(last_two) < 2:
                continue

            if all(_outside(v, lo, hi) for v in last_two):
                latest = FeatureLatest.objects.filter(
                    device=device, feature_name=feature, property_name=prop
                ).first()
                unit = f" {latest.unit}" if latest and latest.unit else ""
                _, created = open_alert(
                    type=AlertType.VALUE_OUT_OF_RANGE,
                    tenant=rule.tenant,
                    device=device,
                    rule=rule,
                    key=key,
                    severity=Severity.WARNING,
                    message=f"{device.display_name}: {feature} = {last_two[0]}{unit} poza zakresem "
                    f"[{lo if lo is not None else '−∞'}, {hi if hi is not None else '∞'}]",
                    details={"values": last_two, "min": lo, "max": hi},
                    email=rule.email_enabled,
                )
                opened += int(created)
            elif not any(_outside(v, lo, hi) for v in last_two):
                close_alerts(
                    type=AlertType.VALUE_OUT_OF_RANGE, tenant=rule.tenant, device=device, key=key
                )
    return opened


def _outside(v: float, lo: float | None, hi: float | None) -> bool:
    return (lo is not None and v < lo) or (hi is not None and v > hi)


def _message_text(row: FeatureLatest) -> str | None:
    """A message feature is "active" when it carries a non-empty value."""
    if row.value_json is not None:
        return (
            json.dumps(row.value_json, ensure_ascii=False, sort_keys=True)
            if row.value_json
            else None
        )
    if row.value_text:
        return (
            row.value_text if row.value_text.lower() not in ("", "none", "off", "false") else None
        )
    if row.value_bool:
        return "true"
    if row.value_num:
        return str(row.value_num)
    return None


def evaluate_messages() -> int:
    """device_message: a feature in group `messages` that carries a value (opens per feature)."""
    opened = 0
    for device in Device.objects.filter(archived_at__isnull=True).select_related("tenant"):
        rules = _rules_for(device, AlertType.DEVICE_MESSAGE)
        rule = rules[0] if rules else None
        if rule is not None and not rule.enabled:
            close_alerts(type=AlertType.DEVICE_MESSAGE, tenant=device.tenant, device=device)
            continue
        active: dict[str, str] = {}
        for row in FeatureLatest.objects.filter(device=device):
            if group_key(row.feature_name) != "messages":
                continue
            text = _message_text(row)
            if text:
                digest = hashlib.sha1(text.encode()).hexdigest()[:12]  # noqa: S324 — dedup only
                active[f"{row.feature_name}:{digest}"] = f"{row.feature_name}: {text[:200]}"
        open_keys = set(
            Alert.objects.filter(
                device=device, type=AlertType.DEVICE_MESSAGE, closed_at__isnull=True
            ).values_list("key", flat=True)
        )
        for key, message in active.items():
            if key in open_keys:
                continue
            _, created = open_alert(
                type=AlertType.DEVICE_MESSAGE,
                tenant=device.tenant,
                device=device,
                rule=rule,
                key=key,
                severity=Severity.WARNING,
                message=f"{device.display_name}: {message}",
                email=rule.email_enabled if rule else True,
            )
            opened += int(created)
        for key in open_keys - set(active):
            close_alerts(
                type=AlertType.DEVICE_MESSAGE, tenant=device.tenant, device=device, key=key
            )
    return opened


def evaluate_provider_accounts() -> int:
    opened = 0
    for account in ProviderAccount.objects.select_related("tenant"):
        key = str(account.id)
        if account.status in (AccountStatus.REAUTH_REQUIRED, AccountStatus.RATE_LIMITED):
            label = (
                "wymaga ponownego logowania"
                if account.status == AccountStatus.REAUTH_REQUIRED
                else "limit API"
            )
            _, created = open_alert(
                type=AlertType.PROVIDER_ACCOUNT,
                tenant=account.tenant,
                key=key,
                severity=Severity.CRITICAL
                if account.status == AccountStatus.REAUTH_REQUIRED
                else Severity.WARNING,
                message=f"Konto {account.provider} ({account.tenant.name}): {label}"
                + (f" — {account.status_reason}" if account.status_reason else ""),
                details={"status": account.status, "account_id": key},
            )
            opened += int(created)
        else:
            close_alerts(type=AlertType.PROVIDER_ACCOUNT, tenant=account.tenant, key=key)
    return opened


def evaluate_workers(now: datetime) -> int:
    """No worker heartbeat for > 2 min → one operator alert (tenant NULL); stale rows pruned.

    Restarted workers leave rows behind (a killed process never gets to the clean shutdown), so
    the condition is "no fresh heartbeat at all", not "this row is stale".
    """
    rows = list(WorkerHeartbeat.objects.all())
    WorkerHeartbeat.objects.filter(last_beat_at__lt=now - STALE_HEARTBEAT_PRUNE).delete()
    fresh = [hb for hb in rows if now - hb.last_beat_at <= WORKER_DOWN_AFTER]
    if fresh or not rows:
        close_alerts(type=AlertType.WORKER_DOWN, tenant=None)
        return 0
    last = max(hb.last_beat_at for hb in rows)
    _, created = open_alert(
        type=AlertType.WORKER_DOWN,
        tenant=None,
        key="all",
        severity=Severity.CRITICAL,
        message=f"Żaden worker nie zgłasza się od {last:%Y-%m-%d %H:%M}",
    )
    return int(created)


def evaluate_backup(now: datetime) -> int:
    """deploy/backup/backup.sh writes `ok <iso> …` or `failed <iso> …`; stale (> 26 h) = failed."""
    from apps.core.api import backup_status

    status = backup_status()
    if status is None:  # no backup service mounted (dev) → nothing to say
        return 0
    words = status.split()
    stale = False
    if len(words) >= 2:
        try:
            stale = now - datetime.fromisoformat(words[1].replace("Z", "+00:00")) > BACKUP_MAX_AGE
        except ValueError:
            stale = True
    if words and words[0] == "ok" and not stale:
        close_alerts(type=AlertType.BACKUP_FAILED, tenant=None)
        return 0
    _, created = open_alert(
        type=AlertType.BACKUP_FAILED,
        tenant=None,
        key="backup",
        severity=Severity.CRITICAL,
        message=f"Backup bazy: {status[:120]}" + (" (przeterminowany)" if stale else ""),
    )
    return int(created)


# --- hooks ---------------------------------------------------------------------------------------


def on_verify_mismatch(command: Any, mismatches: dict[str, Any]) -> Alert:
    """docs/10: verify_mismatch → always, to the author and the operator."""
    author = [command.user.email] if command.user and command.user.email else []
    alert, _ = open_alert(
        type=AlertType.VERIFY_MISMATCH,
        tenant=command.tenant,
        device=command.device,
        key=str(command.id),
        severity=Severity.WARNING,
        message=(
            f"{command.device.display_name}: komenda {command.command_name} "
            f"na {command.feature_name} nie została potwierdzona odczytem"
        ),
        details={"command_id": str(command.id), "mismatches": mismatches},
        extra_recipients=author,
    )
    return alert


def payload(alert: Alert) -> dict[str, Any]:
    return {
        "id": str(alert.id),
        "tenant_id": str(alert.tenant_id) if alert.tenant_id else None,
        "device_id": str(alert.device_id) if alert.device_id else None,
        "device_name": alert.device.display_name if alert.device is not None else None,
        "rule_id": str(alert.rule_id) if alert.rule_id else None,
        "type": alert.type,
        "severity": alert.severity,
        "message": alert.message,
        "details": alert.details,
        "opened_at": alert.opened_at,
        "closed_at": alert.closed_at,
        "acknowledged_at": alert.acknowledged_at,
        "acknowledged_by": (
            alert.acknowledged_by.email if alert.acknowledged_by is not None else None
        ),
        "notified_at": alert.notified_at,
    }


def rule_payload(rule: AlertRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "device_id": str(rule.device_id) if rule.device_id else None,
        "device_name": rule.device.display_name if rule.device is not None else None,
        "type": rule.type,
        "config": rule.config,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
    }
