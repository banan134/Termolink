"""SessionPolicyMiddleware — session max age, last-seen bookkeeping, operator 2FA gate (docs/08).

Placed after TenantContextMiddleware, so the request transaction and RLS context exist.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from .services import TOTP_SETUP_ALLOWED_PATHS, totp_setup_pending, touch_session


class SessionPolicyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            touch_session(request)
            if totp_setup_pending(user) and not request.path.startswith(TOTP_SETUP_ALLOWED_PATHS):
                return JsonResponse(
                    {
                        "error": {
                            "code": "totp_setup_required",
                            "message": "Konto operatora wymaga włączenia 2FA.",
                            "fields": {},
                        }
                    },
                    status=403,
                )
        return self.get_response(request)
