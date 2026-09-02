"""OAuth2 Authorization Code + PKCE for the Viessmann IdP — docs/01 §2 (all [FAKT])."""

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from ..base import AuthError, AuthStart, ProviderTokens, TransientError

SCOPE = "IoT User offline_access"


def make_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def auth_start(iam_base: str, client_id: str, redirect_uri: str, state: str) -> AuthStart:
    verifier, challenge = make_pkce()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return AuthStart(url=f"{iam_base}/authorize?{query}", saved={"code_verifier": verifier})


def _tokens_from(payload: dict[str, Any], previous_refresh: str | None = None) -> ProviderTokens:
    expires_in = payload.get("expires_in")
    return ProviderTokens(
        access_token=payload.get("access_token"),
        access_expires_at=time.time() + float(expires_in) if expires_in else None,
        # docs/01: keep the new refresh token if the IdP rotates it, else the previous one
        refresh_token=payload.get("refresh_token") or previous_refresh or "",
        external_user_id=payload.get("sub") or payload.get("user_id"),
    )


async def _token_request(
    client: httpx.AsyncClient, token_url: str, data: dict[str, str]
) -> dict[str, Any]:
    try:
        response = await client.post(
            token_url, data=data, headers={"Accept": "application/json"}, timeout=15.0
        )
    except httpx.TransportError as exc:
        raise TransientError(f"token endpoint unreachable: {exc}") from exc
    if response.status_code >= 500:
        raise TransientError(f"token endpoint {response.status_code}")
    if response.status_code != 200:
        raise AuthError(f"token endpoint {response.status_code}: {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload, dict) or "access_token" not in payload:
        raise AuthError("token endpoint returned no access_token")
    return payload


async def auth_finish(
    client: httpx.AsyncClient,
    iam_base: str,
    client_id: str,
    redirect_uri: str,
    callback: dict[str, Any],
    saved: dict[str, Any],
) -> ProviderTokens:
    code = callback.get("code")
    if not code:
        raise AuthError(f"callback without code: {callback.get('error') or 'unknown'}")
    payload = await _token_request(
        client,
        f"{iam_base}/token",
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": str(code),
            "code_verifier": str(saved.get("code_verifier", "")),
        },
    )
    return _tokens_from(payload)


async def refresh(
    client: httpx.AsyncClient, iam_base: str, client_id: str, tokens: ProviderTokens
) -> ProviderTokens:
    if not tokens.refresh_token:
        raise AuthError("no refresh token")
    payload = await _token_request(
        client,
        f"{iam_base}/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens.refresh_token,
        },
    )
    return _tokens_from(payload, previous_refresh=tokens.refresh_token)
