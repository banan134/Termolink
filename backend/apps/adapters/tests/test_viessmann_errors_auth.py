"""Error mapping and PKCE auth against a mocked IdP (respx) — no real calls (docs/12)."""

import httpx
import pytest
import respx

from apps.adapters.base import (
    AdapterError,
    AuthError,
    CommandUnsupportedError,
    DeviceOfflineError,
    RateLimitedError,
    TransientError,
)
from apps.adapters.viessmann import auth
from apps.adapters.viessmann.errors import raise_for_response

IAM = "https://iam.example/idp/v3"


def _resp(
    status: int, body: object = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status, json=body, headers=headers, request=httpx.Request("GET", "https://x")
    )


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected"),
    [
        (401, {"error": "unauthorized"}, None, AuthError),
        (429, {"message": "Too Many Requests"}, {"Retry-After": "42"}, RateLimitedError),
        (400, {"message": "You have exceeded your rate limit"}, None, RateLimitedError),
        (
            400,
            {
                "errorType": "DEVICE_COMMUNICATION_ERROR",
                "extendedPayload": {"reason": "GATEWAY_OFFLINE"},
            },
            None,
            DeviceOfflineError,
        ),
        (404, {"errorType": "DEVICE_COMMUNICATION_ERROR"}, None, DeviceOfflineError),
        (502, {"message": "bad gateway"}, None, TransientError),
        (408, None, None, TransientError),
        (400, {"errorType": "OTHER"}, None, AdapterError),
    ],
)
def test_error_mapping(
    status: int, body: object, headers: dict[str, str] | None, expected: type
) -> None:
    with pytest.raises(expected) as exc:
        raise_for_response(_resp(status, body, headers))
    if expected is RateLimitedError and headers:
        assert isinstance(exc.value, RateLimitedError) and exc.value.retry_after_s == 42


def test_command_404_and_endpoint_not_found() -> None:
    with pytest.raises(CommandUnsupportedError):
        raise_for_response(_resp(404, {"message": "not found"}), command=True)
    with pytest.raises(AdapterError) as exc:
        raise_for_response(_resp(404, {"errorType": "ENDPOINT_NOT_FOUND"}))
    assert exc.value.api_changed is True
    raise_for_response(_resp(200, {"data": []}))  # no exception


def test_auth_start_builds_pkce_url() -> None:
    start = auth.auth_start(
        IAM, "client-1", "http://localhost:8080/oauth/viessmann/callback", "st4te"
    )
    assert start.url.startswith(f"{IAM}/authorize?")
    assert "code_challenge_method=S256" in start.url and "scope=IoT+User" in start.url
    assert "state=st4te" in start.url and "client_id=client-1" in start.url
    assert len(start.saved["code_verifier"]) >= 43


@pytest.mark.asyncio
@respx.mock
async def test_auth_finish_and_refresh() -> None:
    route = respx.post(f"{IAM}/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600}
        )
    )
    async with httpx.AsyncClient() as client:
        tokens = await auth.auth_finish(
            client, IAM, "client-1", "http://cb", {"code": "abc"}, {"code_verifier": "v" * 64}
        )
        assert tokens.access_token == "at1" and tokens.refresh_token == "rt1"
        assert tokens.access_expires_at is not None
        sent = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
        assert sent["grant_type"] == "authorization_code" and sent["code_verifier"] == "v" * 64

        route.mock(return_value=httpx.Response(200, json={"access_token": "at2", "expires_in": 60}))
        refreshed = await auth.refresh(client, IAM, "client-1", tokens)
        assert refreshed.access_token == "at2"
        assert refreshed.refresh_token == "rt1"  # not rotated → keep the previous one

        route.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(AuthError):
            await auth.refresh(client, IAM, "client-1", tokens)
        route.mock(return_value=httpx.Response(503))
        with pytest.raises(TransientError):
            await auth.refresh(client, IAM, "client-1", tokens)


@pytest.mark.asyncio
async def test_auth_finish_without_code_is_auth_error() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(AuthError):
            await auth.auth_finish(client, IAM, "c", "http://cb", {"error": "access_denied"}, {})
