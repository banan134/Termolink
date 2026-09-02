"""Normalised provider model and adapter interface — docs/05-adapter-interface.md (verbatim).

Adapters never touch the DB, never count budget, never retry; they map HTTP failures onto the
AdapterError hierarchy and return the full, unfiltered feature list.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ValueType = Literal["number", "string", "boolean", "array", "object", "schedule"]
AuthKind = Literal["oauth2_pkce", "oauth2_client", "api_key", "local"]


@dataclass(frozen=True)
class PropertyDef:
    name: str
    type: ValueType
    unit: str | None
    value: Any  # raw value
    ts_device: str | None  # ISO timestamp from the API, if any


@dataclass(frozen=True)
class ParamDef:
    name: str
    type: ValueType
    required: bool
    constraints: dict[str, Any]  # min, max, stepping, enum, maxLength, + schedule specifics


@dataclass(frozen=True)
class CommandDef:
    name: str
    executable: bool
    params: dict[str, ParamDef]
    uri: str | None  # use the URI returned by the API when present


@dataclass(frozen=True)
class Feature:
    name: str  # exact name from the API
    enabled: bool
    ready: bool
    properties: dict[str, PropertyDef]
    commands: dict[str, CommandDef]
    raw: dict[str, Any]  # original payload (fixtures/diagnostics; not stored outside debug)


@dataclass(frozen=True)
class DeviceDescriptor:
    external_ids: dict[
        str, str
    ]  # e.g. {"installationId": "...", "gatewaySerial": "...", "deviceId": "0"}
    model: str | None
    serial: str | None
    device_type: str | None  # "heatpump", "boiler", "gateway", "unknown", …
    online: bool | None
    raw: dict[str, Any]


@dataclass
class ProviderTokens:
    access_token: str | None
    access_expires_at: float | None  # epoch seconds
    refresh_token: str
    external_user_id: str | None = None


class AdapterError(Exception):
    api_changed: bool = False


class AuthError(AdapterError):
    """→ provider_accounts.status = reauth_required"""


class RateLimitedError(AdapterError):
    def __init__(self, message: str = "rate limited", retry_after_s: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class DeviceOfflineError(AdapterError):
    """→ device status offline"""


class CommandUnsupportedError(AdapterError):
    """404 despite isExecutable → unsupported_commands"""


class TransientError(AdapterError):
    """5xx, timeout → retry"""


@dataclass
class CommandResult:
    ok: bool
    http_status: int | None
    response: dict[str, Any] | None


@dataclass(frozen=True)
class Budget:
    limit: int
    window_s: int
    short_limit: int | None
    short_window_s: int | None


@dataclass(frozen=True)
class AuthStart:
    url: str
    saved: dict[str, Any] = field(default_factory=dict)  # e.g. code_verifier — kept in oauth_states


class ProviderAdapter(Protocol):
    id: str  # "viessmann"
    display_name: str
    auth_kind: AuthKind
    default_budget: Budget

    def auth_start(self, redirect_uri: str, state: str) -> AuthStart: ...

    async def auth_finish(
        self, redirect_uri: str, callback: dict[str, Any], saved: dict[str, Any]
    ) -> ProviderTokens: ...

    async def refresh(self, tokens: ProviderTokens) -> ProviderTokens: ...

    async def discover(self, tokens: ProviderTokens) -> list[DeviceDescriptor]: ...

    async def read_features(
        self, tokens: ProviderTokens, device: DeviceDescriptor
    ) -> list[Feature]:
        """Exactly ONE API call (counted as 1 in the budget)."""
        ...

    async def execute(
        self,
        tokens: ProviderTokens,
        device: DeviceDescriptor,
        feature: Feature,
        command: str,
        params: dict[str, Any],
    ) -> CommandResult:
        """Exactly ONE API call."""
        ...

    def calls_per_read(self) -> int: ...
