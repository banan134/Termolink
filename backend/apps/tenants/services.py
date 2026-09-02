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
