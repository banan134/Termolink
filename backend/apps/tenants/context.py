"""Per-transaction tenant context for PostgreSQL row-level security (docs/03).

The context lives in PostgreSQL session settings scoped to the current transaction
(`set_config(..., is_local=true)` == `SET LOCAL`), so it never leaks between requests or jobs
even with persistent connections.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.db import connection, transaction

ROLE_ANONYMOUS = "anonymous"
ROLE_TENANT = "tenant"
ROLE_OPERATOR = "operator"
ROLE_SYSTEM = "system"


@dataclass(frozen=True)
class TenantContext:
    role: str = ROLE_ANONYMOUS
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    allowed_tenants: tuple[UUID, ...] = field(default_factory=tuple)

    def as_settings(self) -> dict[str, str]:
        return {
            "app.role": self.role,
            "app.tenant_id": str(self.tenant_id) if self.tenant_id else "",
            "app.user_id": str(self.user_id) if self.user_id else "",
            "app.allowed_tenants": ",".join(str(t) for t in self.allowed_tenants),
        }


ANONYMOUS = TenantContext()
SYSTEM = TenantContext(role=ROLE_SYSTEM)


def set_context(ctx: TenantContext) -> None:
    """Apply `ctx` to the current transaction. Must be called inside `transaction.atomic()`."""
    if not connection.in_atomic_block:
        raise RuntimeError("set_context() requires an open transaction (SET LOCAL semantics)")
    with connection.cursor() as cursor:
        for name, value in ctx.as_settings().items():
            cursor.execute("SELECT set_config(%s, %s, true)", [name, value])


def current_context() -> dict[str, str | None]:
    """Read back the context as PostgreSQL sees it (diagnostics and tests)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('app.role', true), current_setting('app.tenant_id', true), "
            "current_setting('app.user_id', true), current_setting('app.allowed_tenants', true)"
        )
        role, tenant_id, user_id, allowed = cursor.fetchone()
    return {
        "role": role,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "allowed_tenants": allowed,
    }


def _set_raw(values: dict[str, str | None]) -> None:
    with connection.cursor() as cursor:
        for name, value in values.items():
            cursor.execute("SELECT set_config(%s, %s, true)", [f"app.{name}", value or ""])


@contextmanager
def system_context() -> Iterator[None]:
    """Run a block with isolation bypassed (role `system`), then restore the previous context.

    This is the only sanctioned way around RLS: session bootstrap, credential lookup on login,
    the worker scheduler and `seed_demo`. Keep the block as small as possible.
    """
    with transaction.atomic():
        previous = current_context()
        set_context(SYSTEM)
        try:
            yield
        finally:
            _set_raw(previous)


def context_for_user(user: Any) -> TenantContext:
    """Build the context for an authenticated (or anonymous) portal user.

    Runs queries for operators (memberships / all tenants), so call it while a `system`
    context is active.
    """
    from apps.accounts.models import Role
    from apps.tenants.models import Tenant, TenantMembership

    if user is None or not getattr(user, "is_authenticated", False):
        return ANONYMOUS
    if user.role == Role.SUPERADMIN:
        allowed = tuple(Tenant.objects.values_list("id", flat=True))
        return TenantContext(role=ROLE_OPERATOR, user_id=user.id, allowed_tenants=allowed)
    if user.role == Role.TECHNICIAN:
        allowed = tuple(
            TenantMembership.objects.filter(user=user).values_list("tenant_id", flat=True)
        )
        return TenantContext(role=ROLE_OPERATOR, user_id=user.id, allowed_tenants=allowed)
    return TenantContext(role=ROLE_TENANT, tenant_id=user.tenant_id, user_id=user.id)
