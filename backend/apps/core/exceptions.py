"""Uniform API error format (docs/04): {"error": {"code", "message", "fields"}}."""

from typing import Any

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

_DEFAULT_CODES = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}


class ApiError(exceptions.APIException):
    """Raise with an explicit machine-readable code and optional extra payload."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        fields: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail=message, code=code)
        self.status_code = status_code
        self.error_code = code
        self.fields = fields or {}
        self.extra = extra or {}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    body: dict[str, Any] = {}
    if isinstance(exc, ApiError):
        body = {"code": exc.error_code, "message": str(exc.detail), "fields": exc.fields}
        body.update(exc.extra)
    elif isinstance(exc, exceptions.ValidationError):
        detail = exc.detail
        fields = detail if isinstance(detail, dict) else {"non_field_errors": detail}
        body = {
            "code": "validation_error",
            "message": "Nieprawidłowe dane.",
            "fields": _flatten(fields),
        }
    elif isinstance(exc, exceptions.Throttled):
        body = {
            "code": "throttled",
            "message": "Zbyt wiele żądań.",
            "fields": {},
            "retry_after_s": getattr(exc, "wait", None),
        }
    else:
        default = getattr(exc, "default_code", None) or _DEFAULT_CODES.get(response.status_code)
        body = {"code": default or "error", "message": _message(exc), "fields": {}}

    response.data = {"error": body}
    return response


def _message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list | tuple) and detail:
        return str(detail[0])
    return str(exc)


def _flatten(fields: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, errors in dict(fields).items():
        if isinstance(errors, list | tuple):
            out[str(name)] = [str(e) for e in errors]
        elif isinstance(errors, dict):
            out[str(name)] = [f"{k}: {v}" for k, v in errors.items()]
        else:
            out[str(name)] = [str(errors)]
    return out
