"""TenantContextMiddleware — docs/03 §Izolacja.

Owns the per-request transaction (replaces ATOMIC_REQUESTS) so that the RLS context set with
SET LOCAL semantics covers the whole view. Order: after AuthenticationMiddleware.
"""

from collections.abc import Callable

from django.db import transaction
from django.http import HttpRequest, HttpResponse

from .context import SYSTEM, context_for_user, set_context


class TenantContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with transaction.atomic():
            # Bootstrap: the session user must be loadable before any tenant context exists.
            set_context(SYSTEM)
            ctx = context_for_user(getattr(request, "user", None))
            set_context(ctx)
            request.tenant_context = ctx  # type: ignore[attr-defined]
            return self.get_response(request)
