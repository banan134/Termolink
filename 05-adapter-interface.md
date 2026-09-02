# 05 — Interfejs adaptera producenta

Cel: dodanie nowego producenta = nowy pakiet w `apps/adapters/<provider>/` + wpis w rejestrze,
bez zmian w UI, bazie, sterowaniu i raportach.

## Znormalizowany model (`apps/adapters/base.py`)

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ValueType = Literal["number", "string", "boolean", "array", "object", "schedule"]

@dataclass(frozen=True)
class PropertyDef:
    name: str
    type: ValueType
    unit: str | None
    value: Any                      # surowa wartość
    ts_device: str | None           # ISO z API, jeśli jest

@dataclass(frozen=True)
class ParamDef:
    name: str
    type: ValueType
    required: bool
    constraints: dict[str, Any]     # min, max, stepping, enum, maxLength, + specyficzne (schedule)

@dataclass(frozen=True)
class CommandDef:
    name: str
    executable: bool
    params: dict[str, ParamDef]
    uri: str | None                 # jeśli API zwraca gotowy URI — używać go

@dataclass(frozen=True)
class Feature:
    name: str                       # dokładna nazwa z API
    enabled: bool
    ready: bool
    properties: dict[str, PropertyDef]
    commands: dict[str, CommandDef]
    raw: dict[str, Any]             # oryginał (do fixtures/diagnostyki; nie zapisywać w DB poza debug)

@dataclass(frozen=True)
class DeviceDescriptor:
    external_ids: dict[str, str]    # np. {"installationId": "...", "gatewaySerial": "...", "deviceId": "0"}
    model: str | None
    serial: str | None
    device_type: str | None         # np. "heatpump", "boiler", "gateway", "unknown"
    online: bool | None
    raw: dict[str, Any]

@dataclass
class ProviderTokens:
    access_token: str | None
    access_expires_at: float | None # epoch
    refresh_token: str
    external_user_id: str | None = None

class AdapterError(Exception): ...
class AuthError(AdapterError): ...            # → reauth_required
class RateLimitedError(AdapterError):
    retry_after_s: int | None
class DeviceOfflineError(AdapterError): ...   # → status offline
class CommandUnsupportedError(AdapterError): ...  # 404 mimo executable → unsupported_commands
class TransientError(AdapterError): ...       # 5xx, timeout → retry

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

class ProviderAdapter(Protocol):
    id: str                                         # "viessmann"
    display_name: str
    auth_kind: Literal["oauth2_pkce", "oauth2_client", "api_key", "local"]
    default_budget: Budget

    def auth_start(self, redirect_uri: str, state: str) -> tuple[str, dict]:
        """→ (url_do_przekierowania, dane_do_zapamiętania np. code_verifier)"""
    async def auth_finish(self, redirect_uri: str, callback: dict, saved: dict) -> ProviderTokens: ...
    async def refresh(self, tokens: ProviderTokens) -> ProviderTokens: ...
    async def discover(self, tokens: ProviderTokens) -> list[DeviceDescriptor]: ...
    async def read_features(self, tokens: ProviderTokens, device: DeviceDescriptor) -> list[Feature]:
        """Dokładnie JEDNO wywołanie API (liczone w budżecie jako 1)."""
    async def execute(self, tokens: ProviderTokens, device: DeviceDescriptor,
                      feature: Feature, command: str, params: dict[str, Any]) -> CommandResult:
        """Dokładnie JEDNO wywołanie API."""
    def calls_per_read(self) -> int: return 1
```

Rejestr: `apps/adapters/registry.py` → `ADAPTERS: dict[str, ProviderAdapter]`; `provider_accounts.provider`
musi być kluczem rejestru.

## Kontrakt zachowań

1. Adapter **nie** liczy budżetu ani nie retry'uje — to robi `ingest`. Adapter mapuje błędy HTTP na
   wyjątki z hierarchii `AdapterError`.
2. Adapter **nie** zapisuje nic do DB.
3. Adapter jest czysty względem tokenów: dostaje `ProviderTokens`, zwraca nowe, jeśli się zmieniły.
4. Adapter musi mieć testy na fixtures z rzeczywistych odpowiedzi (`backend/tests/fixtures/<provider>/*.json`),
   w tym co najmniej: pełna lista cech, odpowiedź `GATEWAY_OFFLINE`, odpowiedź rate-limit, 401.
5. `read_features` zwraca **wszystkie** cechy, bez filtrowania.

## Implementacja Viessmann (`apps/adapters/viessmann/`)

- `client.py` — `httpx.AsyncClient`, timeout 15 s, base URL z `settings.VIESSMANN_API_BASE`,
  IAM URL z `settings.VIESSMANN_IAM_BASE`, `client_id` z env.
- `auth.py` — PKCE (verifier 64 B losowe, challenge S256), `auth_start`, `auth_finish`, `refresh`.
- `parser.py` — surowy JSON cechy → `Feature`. Reguły w `01-viessmann-api.md` §4. Typ `Schedule` → `schedule`.
- `errors.py` — mapowanie: `GATEWAY_OFFLINE` → `DeviceOfflineError`; 401 → `AuthError`;
  429 [ZAŁOŻENIE] lub treść o limicie → `RateLimitedError`; 404 na komendzie → `CommandUnsupportedError`;
  5xx/timeout → `TransientError`; `ENDPOINT_NOT_FOUND` → `AdapterError` z flagą `api_changed=True`.
- `execute` używa `CommandDef.uri` zwróconego przez API; jeśli brak — buduje
  `{base}/features/installations/{i}/gateways/{g}/devices/{d}/features/{feature}/commands/{cmd}`.

## Walidacja parametrów komendy (`apps/control/validation.py`, wspólna dla wszystkich adapterów)

| Typ / constraint | Reguła |
|---|---|
| `number` `min`/`max` | `min ≤ v ≤ max` |
| `number` `stepping` | `(v - min) / stepping` całkowite z tolerancją 1e-9 (gdy brak `min`, względem 0) |
| `string` `enum` | `v in enum` |
| `string` `maxLength` | `len(v) ≤ maxLength` |
| `boolean` | `isinstance(v, bool)` |
| `schedule` | dni ∈ {mon..sun}; każdy wpis `start < end`, format `HH:MM`, `mode ∈ modes`, liczba wpisów ≤ `maxEntries`; brak nakładania, jeśli `overlapAllowed == false` |
| `required` | wszystkie `required` obecne; nieznane parametry → błąd |

Walidacja odbywa się na **ostatnio odczytanej** definicji komendy (`feature_definitions.commands_schema`);
jeśli odczyt starszy niż 30 min → przed wykonaniem wymuszany świeży odczyt (zużywa 1 z rezerwy budżetu).
