"""Device status transitions + device_status_history (docs/06 §Statusy urządzenia)."""

from datetime import datetime

from django.utils import timezone

from apps.devices.models import Device, DeviceStatus, DeviceStatusHistory

ERROR_STREAK_FOR_ERROR_STATUS = 3


def set_status(
    device: Device, status: str, detail: str | None = None, at: datetime | None = None
) -> bool:
    """Transition the device status; returns True when it changed (history row written)."""
    now = at or timezone.now()
    if device.status == status:
        if detail != device.status_detail:
            device.status_detail = detail
            device.save(update_fields=["status_detail", "updated_at"])
        return False
    DeviceStatusHistory.objects.filter(device=device, until__isnull=True).update(until=now)
    DeviceStatusHistory.objects.create(
        tenant=device.tenant, device=device, status=status, since=now, detail=detail
    )
    device.status = status
    device.status_since = now
    device.status_detail = detail
    device.save(update_fields=["status", "status_since", "status_detail", "updated_at"])
    return True


def mark_online(device: Device, at: datetime | None = None) -> bool:
    now = at or timezone.now()
    device.last_seen_at = now
    device.consecutive_errors = 0
    device.save(update_fields=["last_seen_at", "consecutive_errors", "updated_at"])
    return set_status(device, DeviceStatus.ONLINE, None, now)


def mark_offline(device: Device, detail: str, at: datetime | None = None) -> bool:
    device.consecutive_errors = 0
    device.save(update_fields=["consecutive_errors", "updated_at"])
    return set_status(device, DeviceStatus.OFFLINE, detail, at)


def record_error(device: Device, detail: str, at: datetime | None = None) -> bool:
    """Other API errors: `error` after 3 in a row (docs/06)."""
    device.consecutive_errors += 1
    device.save(update_fields=["consecutive_errors", "updated_at"])
    if device.consecutive_errors >= ERROR_STREAK_FOR_ERROR_STATUS:
        return set_status(device, DeviceStatus.ERROR, detail, at)
    return False


def mark_rate_limited(device: Device, at: datetime | None = None) -> bool:
    return set_status(device, DeviceStatus.RATE_LIMITED, "provider rate limit", at)


def check_stale(device: Device, interval_s: int, at: datetime | None = None) -> bool:
    """No successful poll for > 3×interval → offline (docs/06)."""
    now = at or timezone.now()
    if device.status not in (DeviceStatus.ONLINE, DeviceStatus.UNKNOWN):
        return False
    reference = device.last_seen_at or device.created_at
    if reference and (now - reference).total_seconds() > 3 * interval_s:
        return set_status(device, DeviceStatus.OFFLINE, "no successful poll for 3 intervals", now)
    return False
