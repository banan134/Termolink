"""Viessmann adapter — docs/05 §Implementacja Viessmann, docs/01.

Endpoint paths marked [FAKT] in docs/01 §3 are used; `read_features` and `execute` are single
API calls. Parsing lives in parser.py and is validated against the stage-0 fixtures.
"""

from typing import Any

import httpx
from django.conf import settings

from ..base import (
    AuthKind,
    AuthStart,
    Budget,
    CommandResult,
    DeviceDescriptor,
    Feature,
    ProviderTokens,
    TransientError,
)
from . import auth
from .errors import raise_for_response
from .parser import parse_features, parse_installations

TIMEOUT = 15.0


class ViessmannAdapter:
    id: str = "viessmann"
    display_name: str = "Viessmann (ViCare / IoT API)"
    auth_kind: AuthKind = "oauth2_pkce"
    default_budget: Budget = Budget(limit=1450, window_s=86400, short_limit=120, short_window_s=600)

    # --- configuration (env, docs/02 §6) ---
    @property
    def api_base(self) -> str:
        return str(settings.VIESSMANN_API_BASE).rstrip("/")

    @property
    def iam_base(self) -> str:
        return str(settings.VIESSMANN_IAM_BASE).rstrip("/")

    @property
    def client_id(self) -> str:
        return str(settings.VIESSMANN_CLIENT_ID)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT)

    # --- auth ---
    def auth_start(self, redirect_uri: str, state: str) -> AuthStart:
        return auth.auth_start(self.iam_base, self.client_id, redirect_uri, state)

    async def auth_finish(
        self, redirect_uri: str, callback: dict[str, Any], saved: dict[str, Any]
    ) -> ProviderTokens:
        async with self._client() as client:
            return await auth.auth_finish(
                client, self.iam_base, self.client_id, redirect_uri, callback, saved
            )

    async def refresh(self, tokens: ProviderTokens) -> ProviderTokens:
        async with self._client() as client:
            return await auth.refresh(client, self.iam_base, self.client_id, tokens)

    # --- data ---
    async def _get(self, tokens: ProviderTokens, url: str) -> Any:
        async with self._client() as client:
            try:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {tokens.access_token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.TimeoutException as exc:
                raise TransientError(f"timeout: {url}") from exc
            except httpx.TransportError as exc:
                raise TransientError(f"transport: {exc}") from exc
        raise_for_response(response)
        return response.json()

    async def discover(self, tokens: ProviderTokens) -> list[DeviceDescriptor]:
        data = await self._get(
            tokens, f"{self.api_base}/equipment/installations?includeGateways=true"
        )
        return parse_installations(data)

    def features_url(self, device: DeviceDescriptor) -> str:
        ids = device.external_ids
        return (
            f"{self.api_base}/features/installations/{ids['installationId']}"
            f"/gateways/{ids['gatewaySerial']}/devices/{ids['deviceId']}/features"
        )

    async def read_features(
        self, tokens: ProviderTokens, device: DeviceDescriptor
    ) -> list[Feature]:
        data = await self._get(tokens, self.features_url(device))
        return parse_features(data)

    async def execute(
        self,
        tokens: ProviderTokens,
        device: DeviceDescriptor,
        feature: Feature,
        command: str,
        params: dict[str, Any],
    ) -> CommandResult:
        cmd = feature.commands.get(command)
        url = (cmd.uri if cmd and cmd.uri else None) or (
            f"{self.features_url(device)}/{feature.name}/commands/{command}"
        )
        async with self._client() as client:
            try:
                response = await client.post(
                    url,
                    json=params,
                    headers={
                        "Authorization": f"Bearer {tokens.access_token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.TimeoutException as exc:
                raise TransientError(f"timeout: {url}") from exc
            except httpx.TransportError as exc:
                raise TransientError(f"transport: {exc}") from exc
        raise_for_response(response, command=True)
        body: dict[str, Any] | None
        try:
            parsed = response.json()
            body = parsed if isinstance(parsed, dict) else {"data": parsed}
        except ValueError:
            body = None
        return CommandResult(ok=True, http_status=response.status_code, response=body)

    def calls_per_read(self) -> int:
        return 1
