"""SessionPolicyMiddleware — absolute session max age and last-seen bookkeeping (docs/08).

Placed after TenantContextMiddleware, so the request transaction and RLS context exist.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .services import touch_session


class SessionPolicyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            touch_session(request)
        return self.get_response(request)
