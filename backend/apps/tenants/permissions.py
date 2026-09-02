"""RBAC helpers (docs/04 §Uprawnienia, docs/08). Used by views AND services (double check).

Resources outside the caller's scope answer 404, never 403, so their existence is not
revealed. RLS remains the third, independent layer.
"""

from uuid import UUID

from django.http import HttpRequest
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from apps.accounts.models import Role, User
from apps.core.exceptions import ApiError

from .context import ROLE_OPERATOR, TenantContext
from .models import Tenant


def not_found() -> ApiError:
    return ApiError("not_found", "Nie znaleziono.", status_code=404)


def forbidden(code: str = "forbidden", message: str = "Brak uprawnień.") -> ApiError:
    return ApiError(code, message, status_code=403)


def context_of(request: HttpRequest | Request) -> TenantContext:
    raw = getattr(request, "_request", request)
    ctx: TenantContext | None = getattr(raw, "tenant_context", None)
    if ctx is None:
        raise forbidden()
    return ctx


def current_user(request: HttpRequest | Request) -> User:
    user = request.user
    if not isinstance(user, User):
        raise forbidden("not_authenticated", "Wymagane logowanie.")
    return user


def can_access_tenant(request: HttpRequest | Request, tenant_id: UUID) -> bool:
    ctx = context_of(request)
    if ctx.role == ROLE_OPERATOR:
        return tenant_id in ctx.allowed_tenants
    return ctx.tenant_id == tenant_id


def get_tenant_or_404(request: HttpRequest | Request, tenant_id: str | UUID) -> Tenant:
    """Tenant visible to the caller (operator with access or the tenant's own users)."""
    try:
        tid = UUID(str(tenant_id))
    except ValueError as exc:
        raise not_found() from exc
    if not can_access_tenant(request, tid):
        raise not_found()
    tenant = Tenant.objects.filter(id=tid).first()
    if tenant is None:
        raise not_found()
    return tenant


def require_role(request: HttpRequest | Request, *roles: str) -> User:
    user = current_user(request)
    if user.role not in roles:
        raise forbidden()
    return user


def require_tenant_admin_or_operator(request: HttpRequest | Request, tenant: Tenant) -> User:
    user = current_user(request)
    if user.is_operator:
        return user
    if user.role == Role.TENANT_ADMIN and user.tenant_id == tenant.id:
        return user
    raise forbidden()


class IsOperator(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        user = request.user
        return isinstance(user, User) and user.is_operator


class IsSuperadmin(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        user = request.user
        return isinstance(user, User) and user.role == Role.SUPERADMIN
