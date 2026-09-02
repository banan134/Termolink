"""Map Viessmann HTTP responses onto the AdapterError hierarchy (docs/01 §6, docs/05).

Rules marked [ZAŁOŻENIE] in docs/01 are implemented defensively (several signals accepted) and
must be confirmed against the stage-0 fixtures (error_*.json).
"""

from typing import Any

import httpx

from ..base import (
    AdapterError,
    AuthError,
    CommandUnsupportedError,
    DeviceOfflineError,
    RateLimitedError,
    TransientError,
)

RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "too many requests", "quota")


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _retry_after(response: httpx.Response, body: dict[str, Any]) -> int | None:
    header = response.headers.get("Retry-After")
    if header and header.isdigit():
        return int(header)
    payload = body.get("extendedPayload") or {}
    for key in ("retryAfter", "limitReset", "resetAt"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, int | float):
            return int(value)
    return None


def raise_for_response(response: httpx.Response, *, command: bool = False) -> None:
    """Raise the matching AdapterError for a non-2xx response; return silently otherwise."""
    if response.is_success:
        return
    status = response.status_code
    body = _body(response)
    error_type = str(body.get("errorType") or body.get("error") or "")
    reason = ""
    payload = body.get("extendedPayload")
    if isinstance(payload, dict):
        reason = str(payload.get("reason") or "")
    text = (response.text or "")[:500].lower()

    if status == 401:
        raise AuthError(f"401 {error_type or text}")
    if status == 429 or any(marker in text for marker in RATE_LIMIT_MARKERS):
        raise RateLimitedError(
            f"{status} {error_type or 'rate limited'}", _retry_after(response, body)
        )
    if error_type == "DEVICE_COMMUNICATION_ERROR" or reason == "GATEWAY_OFFLINE":
        raise DeviceOfflineError(f"{status} {error_type} {reason}".strip())
    if error_type == "ENDPOINT_NOT_FOUND":
        err = AdapterError(f"{status} ENDPOINT_NOT_FOUND — possible API change")
        err.api_changed = True
        raise err
    if status == 404 and command:
        raise CommandUnsupportedError(f"404 on command: {error_type or text}")
    if status >= 500 or status == 408:
        raise TransientError(f"{status} {error_type or text}")
    raise AdapterError(f"{status} {error_type or text}")
