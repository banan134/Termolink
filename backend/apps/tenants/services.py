"""Tenant management services (docs/04 §Operator: klienci). Views call these."""

from typing import Any
from uuid import UUID

from django.http import HttpRequest

from apps.accounts.models import Invitation, Role, User
from apps.accounts.services import issue_invitation
from apps.audit.services import audit
from apps.core.exceptions import ApiError

from .context import ROLE_OPERATOR, context_of, system_context
from .models import Tenant, TenantMembership

EDITABLE_TENANT_FIELDS = ("name", "type", "control_allowed", "report_header_text", "timezone")
INVITABLE_BY_TENANT_ADMIN = {Role.TENANT_ADMIN, Role.TENANT_USER}


def visible_tenants(request: HttpRequest) -> list[Tenant]:
    ctx = context_of(request)
    if ctx.role != ROLE_OPERATOR:
        return []
    return list(Tenant.objects.filter(id__in=ctx.allowed_tenants).order_by("name"))


def create_tenant(request: HttpRequest, *, actor: User, **fields: Any) -> Tenant:
    if actor.role != Role.SUPERADMIN:
        raise ApiError("forbidden", "Tylko superadmin tworzy klientów.", status_code=403)
    tenant = Tenant.objects.create(**{k: v for k, v in fields.items() if v is not None})
    audit("tenant.created", request=request, user=actor, tenant=tenant, target=tenant)
    return tenant


def update_tenant(request: HttpRequest, *, actor: User, tenant: Tenant, **fields: Any) -> Tenant:
    changes = {k: v for k, v in fields.items() if k in EDITABLE_TENANT_FIELDS and v is not None}
    for key, value in changes.items():
        setattr(tenant, key, value)
    if changes:
        tenant.save(update_fields=[*changes, "updated_at"])
        audit(
            "tenant.updated",
            request=request,
            user=actor,
            tenant=tenant,
            target=tenant,
            details={"fields": sorted(changes)},
        )
    return tenant


def tenant_users(tenant: Tenant) -> list[User]:
    return list(User.objects.filter(tenant=tenant).order_by("email"))


def invite_to_tenant(
    request: HttpRequest, *, actor: User, tenant: Tenant, email: str, role: str
) -> Invitation:
    if role not in INVITABLE_BY_TENANT_ADMIN:
        raise ApiError(
            "validation_error",
            "Nieprawidłowa rola.",
            fields={"role": ["Dozwolone: tenant_admin, tenant_user."]},
        )
    if User.objects.filter(email=email.lower()).exists():
        raise ApiError("email_taken", "Konto z tym adresem już istnieje.", status_code=409)
    Invitation.objects.filter(email=email.lower(), accepted_at__isnull=True).delete()
    return issue_invitation(email=email, role=role, tenant=tenant, created_by=actor)


def pending_invitations(tenant: Tenant) -> list[Invitation]:
    return list(
        Invitation.objects.filter(tenant=tenant, accepted_at__isnull=True).order_by("-created_at")
    )


# --- technician memberships (superadmin) -----------------------------------------------------


def technician_or_404(user_id: str | UUID) -> User:
    try:
        uid = UUID(str(user_id))
    except ValueError as exc:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404) from exc
    with system_context():
        user = User.objects.filter(id=uid, role=Role.TECHNICIAN).first()
    if user is None:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404)
    return user


def list_memberships(technician: User) -> list[TenantMembership]:
    with system_context():
        return list(
            TenantMembership.objects.filter(user=technician)
            .select_related("tenant")
            .order_by("tenant__name")
        )


def set_membership(
    request: HttpRequest, *, actor: User, technician: User, tenant: Tenant, can_control: bool
) -> TenantMembership:
    with system_context():
        row, created = TenantMembership.objects.update_or_create(
            user=technician, tenant=tenant, defaults={"can_control": can_control}
        )
    audit(
        "membership.set",
        request=request,
        user=actor,
        tenant=tenant,
        target=row,
        details={"technician": technician.email, "can_control": can_control, "created": created},
    )
    return row


def remove_membership(
    request: HttpRequest, *, actor: User, technician: User, tenant: Tenant
) -> None:
    with system_context():
        deleted, _ = TenantMembership.objects.filter(user=technician, tenant=tenant).delete()
    if not deleted:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404)
    audit(
        "membership.removed",
        request=request,
        user=actor,
        tenant=tenant,
        details={"technician": technician.email},
    )


# ---------- logo (report header) ----------
LOGO_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}


def _logo_kind(head: bytes) -> str | None:
    for signature, ext in LOGO_SIGNATURES.items():
        if head.startswith(signature):
            return ext
    return None


def set_logo(request: Any, *, actor: Any, tenant: Tenant, upload: Any) -> Tenant:
    """PNG/JPEG ≤ 1 MB, verified by magic bytes (not by extension/Content-Type). SVG rejected."""
    from pathlib import Path

    from django.conf import settings

    from apps.core.exceptions import ApiError

    if upload.size > settings.LOGO_MAX_BYTES:
        raise ApiError(
            "validation_error", "Plik za duży (max 1 MB).", fields={"file": ["max 1 MB"]}
        )
    head = upload.read(16)
    upload.seek(0)
    kind = _logo_kind(head)
    if kind is None:
        raise ApiError(
            "validation_error",
            "Dozwolone tylko PNG lub JPEG.",
            fields={"file": ["PNG lub JPEG (SVG niedozwolone)"]},
        )
    rel = f"logos/{tenant.id}.{kind}"
    target = Path(settings.MEDIA_ROOT) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    for other in ("png", "jpg"):
        if other != kind:
            stale = Path(settings.MEDIA_ROOT) / f"logos/{tenant.id}.{other}"
            if stale.exists():
                stale.unlink()
    tenant.logo_path = rel
    tenant.save(update_fields=["logo_path", "updated_at"])
    audit(
        "tenant.logo.set",
        request=request,
        user=actor,
        tenant=tenant,
        target=tenant,
        details={"path": rel},
    )
    return tenant


def remove_logo(request: Any, *, actor: Any, tenant: Tenant) -> Tenant:
    from pathlib import Path

    from django.conf import settings

    if tenant.logo_path:
        path = Path(settings.MEDIA_ROOT) / tenant.logo_path
        if path.exists():
            path.unlink()
    tenant.logo_path = None
    tenant.save(update_fields=["logo_path", "updated_at"])
    audit("tenant.logo.removed", request=request, user=actor, tenant=tenant, target=tenant)
    return tenant


# ---------- permanent deletion (operator) ----------
def delete_tenant(request: HttpRequest, *, actor: User, tenant: Tenant) -> None:
    """Hard delete: every row of the tenant, incl. the Timescale history (no FK there) and files.

    Superadmin only (checked by the view). Audit rows keep tenant_id NULL-able: the audit entry
    is written with the tenant name in details so the trail survives the cascade.
    """
    import shutil
    from pathlib import Path

    from django.conf import settings
    from django.db import connection

    if actor.role != Role.SUPERADMIN:
        raise ApiError("forbidden", "Tylko superadmin może usunąć klienta.", status_code=403)
    name, tenant_id = tenant.name, tenant.id
    from apps.devices.models import Device
    from apps.providers.models import ProviderAccount

    with system_context(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM feature_values_rls WHERE tenant_id = %s", [tenant_id])
        # (feature_values itself is not granted to the app role — only the *_rls view; docs/03)
        # PROTECT foreign keys (devices → accounts, users → tenant): explicit order
        Device.objects.filter(tenant=tenant).delete()
        ProviderAccount.objects.filter(tenant=tenant).delete()
        TenantMembership.objects.filter(tenant=tenant).delete()
        User.objects.filter(tenant=tenant).delete()
        for folder in ("logos", "reports"):
            path = Path(settings.MEDIA_ROOT) / folder / str(tenant_id)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        if tenant.logo_path:
            logo = Path(settings.MEDIA_ROOT) / tenant.logo_path
            if logo.exists():
                logo.unlink()
        tenant.delete()
    audit(
        "tenant.deleted",
        request=request,
        user=actor,
        details={"tenant_id": str(tenant_id), "name": name},
    )
