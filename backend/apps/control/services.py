"""Control flow — docs/07-control-flow.md. Every rule is enforced here (views only call in)."""

import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.adapters.base import (
    AdapterError,
    AuthError,
    CommandDef,
    CommandUnsupportedError,
    Feature,
    ParamDef,
    RateLimitedError,
    TransientError,
)
from apps.adapters.registry import get_adapter
from apps.audit.services import audit
from apps.core.exceptions import ApiError
from apps.devices import labels as label_dict
from apps.devices.models import Device, DeviceMode, DeviceStatus, FeatureDefinition, FeatureLatest
from apps.ingest import queue
from apps.ingest.models import Job
from apps.ingest.poller import descriptor_for, poll_device
from apps.providers import budget
from apps.providers.models import CallKind
from apps.providers.services import ensure_fresh_tokens, mark_rate_limited, mark_reauth_required
from apps.tenants.models import TenantMembership

from .models import Command, CommandStatus
from .validation import numbers_match, validate_params

DRAFT_TTL = timedelta(minutes=5)
STALE_DEFINITION = timedelta(minutes=30)
VERIFY_DELAY_S = 60
VERIFY_MAX_ATTEMPTS = 3
SENSITIVE_HINTS = ("standby", "off")


# --- who may control (docs/07 §Kto może wykonać komendę) --------------------------------------


def can_control(user: User, device: Device) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if device.mode != DeviceMode.CONTROL:
        reasons.append("device_read_only")
    if not device.tenant.control_allowed:
        reasons.append("tenant_control_blocked")
    if user.role == Role.SUPERADMIN:
        pass
    elif user.role == Role.TECHNICIAN:
        if not TenantMembership.objects.filter(
            user=user, tenant=device.tenant, can_control=True
        ).exists():
            reasons.append("operator_no_control_permission")
    elif user.role == Role.TENANT_ADMIN:
        if not user.totp_enabled:
            reasons.append("totp_required")
    else:
        reasons.append("role_not_allowed")
    if device.status != DeviceStatus.ONLINE:
        reasons.append("device_not_online")
    since = timezone.now() - timedelta(hours=1)
    recent = Command.objects.filter(
        device=device,
        created_at__gte=since,
        status__in=[CommandStatus.SUCCEEDED, CommandStatus.VERIFY_PENDING, CommandStatus.VERIFIED],
    ).count()
    if recent >= device.commands_per_hour_limit:
        reasons.append("hourly_limit_reached")
    if budget.available_for_reserve(device.provider_account) < 2:
        reasons.append("budget_reserve_exhausted")
    return (not reasons, reasons)


def is_sensitive(command_name: str, schema: dict[str, Any]) -> bool:
    """docs/07 §Komendy wrażliwe: configured names + anything mentioning standby/off in an enum."""
    if command_name in settings.SENSITIVE_COMMANDS:
        return True
    lowered = command_name.lower()
    if any(hint in lowered for hint in SENSITIVE_HINTS):
        return True
    for param in (schema.get("params") or {}).values():
        for option in (param.get("constraints") or {}).get("enum") or []:
            if any(hint in str(option).lower() for hint in SENSITIVE_HINTS):
                return True
    return False


# --- draft ---------------------------------------------------------------------------------------


def _property_for_param(
    feature_name: str, command_name: str, param: str, latest: dict[str, Any]
) -> str | None:
    label = label_dict.resolve(feature_name)
    mapping = (label.command_property_map.get(command_name) if label else None) or {}
    if param in mapping:
        return mapping[param]
    if param in latest:  # same name (docs/07 default)
        return param
    if len(latest) == 1 and param in ("value", "temperature", "targetTemperature", "mode", "name"):
        return next(iter(latest))
    return None


def _latest_values(device: Device, feature_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in FeatureLatest.objects.filter(device=device, feature_name=feature_name):
        out[row.property_name] = (
            row.value_num
            if row.value_num is not None
            else row.value_bool
            if row.value_bool is not None
            else row.value_text
            if row.value_text is not None
            else row.value_json
        )
    return out


def create_draft(
    request: HttpRequest,
    *,
    user: User,
    device: Device,
    feature_name: str,
    command_name: str,
    params: dict[str, Any],
) -> Command:
    ok, reasons = can_control(user, device)
    if not ok:
        raise ApiError(
            "control_not_allowed",
            "Sterowanie niedozwolone.",
            status_code=403,
            extra={"reasons": reasons},
        )

    definition = FeatureDefinition.objects.filter(device=device, feature_name=feature_name).first()
    if definition is None:
        raise ApiError(
            "command_not_available", "Cecha nie istnieje na tym urządzeniu.", status_code=422
        )
    if timezone.now() - definition.last_seen_at > STALE_DEFINITION:
        # docs/07: definition older than 30 min → forced fresh read (reserve) before validation
        poll_device(device, kind=CallKind.REFRESH)
        definition.refresh_from_db()
        device.refresh_from_db()
    schema = definition.commands_schema.get(command_name)
    if (
        not schema
        or not schema.get("isExecutable")
        or command_name in definition.unsupported_commands
    ):
        raise ApiError(
            "command_not_available", "Komenda niedostępna dla tej cechy.", status_code=422
        )

    errors = validate_params(schema, params)
    if errors:
        raise ApiError(
            "constraint_violation",
            "Parametry poza dozwolonym zakresem.",
            status_code=422,
            fields=dict(errors),
        )

    latest = _latest_values(device, feature_name)
    value_before: dict[str, Any] = {}
    for param in params:
        prop = _property_for_param(feature_name, command_name, param, latest)
        if prop is not None:
            value_before[prop] = latest.get(prop)
    sensitive = is_sensitive(command_name, schema)
    command = Command.objects.create(
        tenant=device.tenant,
        device=device,
        user=user,
        acted_as_operator=user.is_operator,
        feature_name=feature_name,
        command_name=command_name,
        params=params,
        value_before=value_before,
        value_after=params,
        sensitive=sensitive,
        ip=_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        expires_at=timezone.now() + DRAFT_TTL,
    )
    audit(
        "command.draft",
        request=request,
        user=user,
        tenant=device.tenant,
        target=command,
        details=_details(command),
    )
    return command


# --- confirm -------------------------------------------------------------------------------------


def confirm(request: HttpRequest, *, user: User, command: Command) -> Command:
    from apps.accounts.services import has_valid_reauth

    if command.status != CommandStatus.DRAFT or command.user_id != user.id:
        raise ApiError(
            "command_state", "Komenda nie jest szkicem tego użytkownika.", status_code=409
        )
    if command.expires_at < timezone.now():
        command.status = CommandStatus.EXPIRED
        command.save(update_fields=["status"])
        raise ApiError(
            "command_expired", "Szkic wygasł — utwórz komendę ponownie.", status_code=409
        )
    if command.sensitive and not has_valid_reauth(request):
        raise ApiError(
            "reauth_required",
            "Komenda wrażliwa wymaga ponownego uwierzytelnienia.",
            status_code=428,
        )
    ok, reasons = can_control(user, command.device)
    if not ok:
        raise ApiError(
            "control_not_allowed",
            "Sterowanie niedozwolone.",
            status_code=403,
            extra={"reasons": reasons},
        )
    with transaction.atomic():
        command.status = CommandStatus.CONFIRMED
        command.reauth_verified = command.sensitive
        command.confirmed_at = timezone.now()
        command.save(update_fields=["status", "reauth_verified", "confirmed_at"])
        queue.enqueue(
            "execute_command",
            {"command_id": str(command.id)},
            tenant=command.tenant,
            provider_account_id=command.device.provider_account_id,
            created_by=user,
            priority=10,
        )
    audit(
        "command.confirmed",
        request=request,
        user=user,
        tenant=command.tenant,
        target=command,
        details=_details(command),
    )
    return command


# --- jobs ----------------------------------------------------------------------------------------


def _feature_from_definition(definition: FeatureDefinition) -> Feature:
    commands = {
        name: CommandDef(
            name=name,
            executable=bool(c.get("isExecutable")),
            params={
                p: ParamDef(
                    p,
                    d.get("type", "object"),
                    bool(d.get("required")),
                    dict(d.get("constraints") or {}),
                )
                for p, d in (c.get("params") or {}).items()
            },
            uri=definition.command_uris.get(name),
        )
        for name, c in definition.commands_schema.items()
    }
    return Feature(
        name=definition.feature_name,
        enabled=definition.is_enabled,
        ready=definition.is_ready,
        properties={},
        commands=commands,
        raw={},
    )


def execute(command: Command) -> dict[str, Any]:
    """Job execute_command (docs/07): one API call from the reserve, then schedule verify."""
    if command.status != CommandStatus.CONFIRMED:
        return {"skipped": command.status}
    device = command.device
    account = device.provider_account
    call = budget.try_acquire(account.id, CallKind.COMMAND, device_id=device.id)
    if call is None:
        age = timezone.now() - (command.confirmed_at or command.created_at)
        if age > timedelta(minutes=5):
            _finish(command, CommandStatus.FAILED, reject_reason="budget")
            return {"status": "failed", "reason": "budget"}
        raise TransientError("no reserve budget; retry")
    definition = FeatureDefinition.objects.filter(
        device=device, feature_name=command.feature_name
    ).first()
    if definition is None:
        budget.finish_call(call, http_status=None, duration_ms=0, error_type="no_definition")
        _finish(command, CommandStatus.FAILED, reject_reason="feature missing")
        return {"status": "failed"}
    Command.objects.filter(id=command.id).update(status=CommandStatus.EXECUTING)
    started = time.monotonic()
    try:
        tokens = ensure_fresh_tokens(account)
        result = async_to_sync(get_adapter(device.provider).execute)(
            tokens,
            descriptor_for(device),
            _feature_from_definition(definition),
            command.command_name,
            command.params,
        )
    except CommandUnsupportedError as exc:
        budget.finish_call(
            call, http_status=404, duration_ms=_ms(started), error_type="unsupported"
        )
        if command.command_name not in definition.unsupported_commands:
            definition.unsupported_commands = [
                *definition.unsupported_commands,
                command.command_name,
            ]
            definition.save(update_fields=["unsupported_commands"])
        _finish(command, CommandStatus.FAILED, api_status=404, reject_reason=str(exc)[:200])
        audit(
            "command.unsupported",
            tenant=command.tenant,
            target=command,
            details={**_details(command), "error": str(exc)[:200]},
        )
        return {"status": "failed", "reason": "unsupported"}
    except AuthError as exc:
        budget.finish_call(call, http_status=401, duration_ms=_ms(started), error_type="auth")
        mark_reauth_required(account, str(exc)[:200])
        _finish(command, CommandStatus.FAILED, api_status=401, reject_reason="reauth_required")
        return {"status": "failed", "reason": "auth"}
    except RateLimitedError as exc:
        budget.finish_call(
            call, http_status=429, duration_ms=_ms(started), error_type="rate_limited"
        )
        mark_rate_limited(account, exc.retry_after_s)
        _finish(command, CommandStatus.FAILED, api_status=429, reject_reason="rate_limited")
        return {"status": "failed", "reason": "rate_limited"}
    except TransientError as exc:
        budget.finish_call(call, http_status=None, duration_ms=_ms(started), error_type="transient")
        Command.objects.filter(id=command.id).update(status=CommandStatus.CONFIRMED)
        raise TransientError(str(exc)) from exc
    except AdapterError as exc:
        budget.finish_call(
            call, http_status=None, duration_ms=_ms(started), error_type=type(exc).__name__
        )
        _finish(command, CommandStatus.FAILED, reject_reason=str(exc)[:200])
        return {"status": "failed", "reason": str(exc)[:200]}
    budget.finish_call(call, http_status=result.http_status, duration_ms=_ms(started))
    now = timezone.now()
    Command.objects.filter(id=command.id).update(
        status=CommandStatus.SUCCEEDED,
        api_status=result.http_status,
        api_response=result.response,
        executed_at=now,
    )
    command.refresh_from_db()
    audit(
        "command.succeeded",
        tenant=command.tenant,
        user=command.user,
        target=command,
        details={**_details(command), "api_status": result.http_status},
    )
    queue.enqueue(
        "verify_command",
        {"command_id": str(command.id)},
        tenant=command.tenant,
        provider_account_id=account.id,
        run_at=now + timedelta(seconds=VERIFY_DELAY_S),
        priority=20,
    )
    return {"status": "succeeded", "api_status": result.http_status}


def verify(command: Command) -> dict[str, Any]:
    """Job verify_command (docs/07): fresh read, compare value_after with feature_latest."""
    if command.status not in (CommandStatus.SUCCEEDED, CommandStatus.VERIFY_PENDING):
        return {"skipped": command.status}
    device = command.device
    account = device.provider_account
    command.verify_attempts += 1
    command.save(update_fields=["verify_attempts"])
    call = budget.try_acquire(account.id, CallKind.VERIFY, device_id=device.id)
    if call is None:
        if command.verify_attempts >= VERIFY_MAX_ATTEMPTS:
            Command.objects.filter(id=command.id).update(status=CommandStatus.VERIFY_PENDING)
            return {"status": "verify_pending"}
        raise TransientError("no reserve budget for verify; retry")
    # poll_device already acquired? No — it acquires its own call; release ours first
    budget.finish_call(call, http_status=None, duration_ms=0, error_type="superseded")
    result = poll_device(device, kind=CallKind.VERIFY)
    if result.get("status") != "online":
        if command.verify_attempts >= VERIFY_MAX_ATTEMPTS:
            Command.objects.filter(id=command.id).update(status=CommandStatus.VERIFY_PENDING)
            return {"status": "verify_pending", "poll": result}
        raise TransientError(f"verify read failed: {result}")
    return compare_with_latest(command)


def compare_with_latest(command: Command) -> dict[str, Any]:
    """Also used after a regular poll for verify_pending commands (docs/07)."""
    definition = FeatureDefinition.objects.filter(
        device=command.device, feature_name=command.feature_name
    ).first()
    schema = (definition.commands_schema.get(command.command_name) if definition else None) or {}
    latest = _latest_values(command.device, command.feature_name)
    mismatches: dict[str, Any] = {}
    for param, expected in (command.value_after or {}).items():
        prop = _property_for_param(command.feature_name, command.command_name, param, latest)
        if prop is None:
            continue
        stepping = (
            ((schema.get("params") or {}).get(param) or {}).get("constraints", {}).get("stepping")
        )
        actual = latest.get(prop)
        if not numbers_match(expected, actual, stepping):
            mismatches[prop] = {"expected": expected, "actual": actual}
    now = timezone.now()
    if mismatches:
        Command.objects.filter(id=command.id).update(
            status=CommandStatus.VERIFY_MISMATCH, verified_at=now
        )
        audit(
            "command.verify_mismatch",
            tenant=command.tenant,
            user=command.user,
            target=command,
            details={**_details(command), "mismatches": mismatches},
        )
        return {"status": "verify_mismatch", "mismatches": mismatches}
    Command.objects.filter(id=command.id).update(status=CommandStatus.VERIFIED, verified_at=now)
    audit(
        "command.verified",
        tenant=command.tenant,
        user=command.user,
        target=command,
        details=_details(command),
    )
    return {"status": "verified"}


def settle_pending_after_poll(device: Device) -> int:
    """Called by the poller: verify_pending commands get their verdict from the regular read."""
    n = 0
    for command in Command.objects.filter(device=device, status=CommandStatus.VERIFY_PENDING):
        compare_with_latest(command)
        n += 1
    return n


def expire_drafts() -> int:
    return Command.objects.filter(status=CommandStatus.DRAFT, expires_at__lt=timezone.now()).update(
        status=CommandStatus.EXPIRED
    )


# --- helpers -------------------------------------------------------------------------------------


def _finish(
    command: Command,
    status: str,
    *,
    api_status: int | None = None,
    reject_reason: str | None = None,
) -> None:
    Command.objects.filter(id=command.id).update(
        status=status,
        api_status=api_status,
        reject_reason=reject_reason,
        executed_at=timezone.now(),
    )
    command.refresh_from_db()
    audit(
        f"command.{status}",
        tenant=command.tenant,
        user=command.user,
        target=command,
        details={**_details(command), "reason": reject_reason},
    )


def _details(command: Command) -> dict[str, Any]:
    return {
        "device": str(command.device_id),
        "feature": command.feature_name,
        "command": command.command_name,
        "params": command.params,
        "value_before": command.value_before,
        "sensitive": command.sensitive,
        "acted_as_operator": command.acted_as_operator,
    }


def _ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def payload(command: Command) -> dict[str, Any]:
    return {
        "id": str(command.id),
        "device_id": str(command.device_id),
        "feature_name": command.feature_name,
        "command_name": command.command_name,
        "params": command.params,
        "value_before": command.value_before,
        "value_after": command.value_after,
        "status": command.status,
        "sensitive": command.sensitive,
        "reject_reason": command.reject_reason,
        "api_status": command.api_status,
        "user_email": command.user.email if command.user else None,
        "acted_as_operator": command.acted_as_operator,
        "created_at": command.created_at,
        "expires_at": command.expires_at,
        "confirmed_at": command.confirmed_at,
        "executed_at": command.executed_at,
        "verified_at": command.verified_at,
    }


def get_command_or_404(tenant_id: UUID, command_id: str | UUID) -> Command:
    try:
        command = Command.objects.select_related("device", "user", "tenant").get(
            id=UUID(str(command_id)), tenant_id=tenant_id
        )
    except (Command.DoesNotExist, ValueError) as exc:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404) from exc
    return reconcile(command)


def reconcile(command: Command) -> Command:
    """A command whose job died (all retries failed) must not stay "confirmed" forever."""
    if command.status in (
        CommandStatus.CONFIRMED,
        CommandStatus.EXECUTING,
        CommandStatus.SUCCEEDED,
    ):
        job = job_for(command)
        if job is not None and job.status == "failed":
            _finish(
                command, CommandStatus.FAILED, reject_reason=f"job_failed: {job.last_error}"[:200]
            )
    return command


def job_for(command: Command) -> Job | None:
    return (
        Job.objects.filter(
            kind__in=["execute_command", "verify_command"], payload__command_id=str(command.id)
        )
        .order_by("-id")
        .first()
    )
