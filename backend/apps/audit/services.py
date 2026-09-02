"""`audit(action, target, details)` — the one way to write the audit log (docs/03, docs/08).

Writes always happen in the `system` RLS context so that pre-auth events (failed logins,
password resets) and cross-tenant operator actions are recorded regardless of the caller's
context. Secrets must never be passed in `details`.
"""

from typing import Any
from uuid import UUID

from django.db import models
from django.http import HttpRequest

from apps.tenants.context import system_context

from .models import AuditLog


def audit(
    action: str,
    *,
    request: HttpRequest | None = None,
    user: Any | None = None,
    tenant: Any | None = None,
    target: models.Model | None = None,
    target_type: str | None = None,
    target_id: UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and getattr(candidate, "is_authenticated", False):
            user = candidate
    if tenant is None and user is not None:
        tenant = getattr(user, "tenant", None)
    if target is not None:
        target_type = target_type or target._meta.db_table
        target_id = target_id or getattr(target, "pk", None)
    ip = _client_ip(request) if request is not None else None

    with system_context():
        return AuditLog.objects.create(
            tenant=tenant,
            user=user,
            action=action,
            target_type=target_type or "",
            target_id=UUID(str(target_id)) if target_id else None,
            details=details or {},
            ip=ip,
        )


def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None
