# 01 — API Viessmann: fakty, założenia, do weryfikacji

> **Status źródeł.** Oficjalna dokumentacja (https://api.viessmann-climatesolutions.com/documentation)
> jest aplikacją JS i nie została odczytana automatycznie. Poniższe informacje pochodzą z:
> FAQ i cennika portalu deweloperskiego Viessmann, dokumentacji integracji `vicare` w Home Assistant,
> README oraz danych testowych biblioteki PyViCare (github.com/openviess/PyViCare).
> Od 3 września 2026 dochodzą **własne zrzuty etapu 0** (`backend/tests/fixtures/viessmann/`,
> `capture_report.json`): instalacja z bramką TCU200 (`E3_TCU19_x05`), kotłem `E3_Vitodens_200_0421`
> (181 cech) i `E3_RoomControl_One_19_04` (363 cechy).
> Oznaczenia: **[FAKT]** — potwierdzone w źródle; **[FAKT 2026-09-03]** — potwierdzone własnym zrzutem;
> **[ZAŁOŻENIE]** — do weryfikacji.
> **Nie implementuj niczego oznaczonego [ZAŁOŻENIE] jako pewnik — dodaj test na rzeczywistym zrzucie.**

## 1. Rejestracja klienta API

- **[FAKT]** Logowanie do portalu deweloperskiego tym samym kontem co aplikacja ViCare.
- **[FAKT]** W dashboardzie tworzy się „API client” z nazwą i **Redirect URI**; klient może być
  aktywny dopiero po ok. godzinie.
- **[FAKT]** Redirect URI musi dokładnie odpowiadać temu, którego używa aplikacja; niezgodność daje
  błąd „Invalid redirection URI”.
- Termolink używa: `https://<domena>/oauth/viessmann/callback` (produkcja) oraz
  `http://localhost:8080/oauth/viessmann/callback` (dev, przez proxy Caddy — `15-local-development.md`) — **oba muszą być wpisane w portalu Viessmann**.

**ZAŁOŻENIE (2026-09-04): `prompt=login` w `/authorize`.** IAM Viessmann pamięta sesję przeglądarki
(SSO) i przy kolejnym „Podłącz konto” od razu zwraca `code` bez ekranu logowania — operator nie może
wtedy podłączyć innego konta klienta ze swojej przeglądarki. Termolink dodaje standardowy parametr
OIDC `prompt=login`; do sprawdzenia, czy IAM go honoruje (jeśli nie: okno prywatne lub wylogowanie
z ViCare przed podłączeniem — instrukcja w UI).

## 2. Autoryzacja (OAuth2 Authorization Code + PKCE)

| Element | Wartość | Status |
|---|---|---|
| Authorization URL | `https://iam.viessmann-climatesolutions.com/idp/v3/authorize` | [FAKT] |
| Token URL | `https://iam.viessmann-climatesolutions.com/idp/v3/token` | [FAKT] |
| Scope | `IoT User` | [FAKT] |
| Client secret | brak (PKCE) | [FAKT] |
| PKCE | `code_challenge_method=S256` | [FAKT] |
| Scope | `IoT User offline_access` (bez `offline_access` brak refresh tokena) | [FAKT 2026-09-03] |
| Czas życia access tokena | `expires_in = 3600` s | [FAKT 2026-09-03] |
| Czas życia refresh tokena | nieznany (obserwować; wg HA ok. 180 dni) | [ZAŁOŻENIE] |
| Rotacja refresh tokena przy odświeżeniu | **nie rotuje**; odświeżenie daje nowy access token, `expires_in 3600` | [FAKT 2026-09-03] |
| Odpowiedź tokena | `access_token`, `expires_in`, `refresh_token`, `token_type=Bearer` (brak `scope`, brak `sub`) | [FAKT 2026-09-03] |

Przebieg:

```
1. GET {auth_url}?response_type=code&client_id={id}&redirect_uri={uri}
       &scope=IoT%20User&code_challenge={S256(verifier)}&code_challenge_method=S256&state={state}
2. Użytkownik loguje się w Viessmann → redirect na redirect_uri?code=...&state=...
3. POST {token_url}  grant_type=authorization_code&client_id&redirect_uri&code&code_verifier
   → { access_token, refresh_token, expires_in, ... }
4. Odświeżanie: POST {token_url} grant_type=refresh_token&client_id&refresh_token
```

Implementacja: odświeżać proaktywnie (np. 60 s przed `expires_in`) **i** reaktywnie po HTTP 401.
Nieudane odświeżenie → `provider_accounts.status = 'reauth_required'` + alert dla operatora.

## 3. Endpointy IoT

Base URL: `https://api.viessmann-climatesolutions.com/iot/v2` **[FAKT 2026-09-03]** — `/iot/v1/equipment/installations`
odpowiada `410 GONE` (`errorType: GONE`, `sunsetDate 2025-12-15`, `extendedPayload.replacement:
"GET /iot/v2/equipment/installations"`); skrypt etapu 0 podąża za zamiennikiem i zapisuje go w raporcie.

| Cel | Endpoint | Status |
|---|---|---|
| Lista instalacji z bramami i urządzeniami | `GET /equipment/installations?includeGateways=true` → `{cursor, data[]}` | [FAKT 2026-09-03] |
| Wszystkie cechy urządzenia (1 wywołanie) | `GET /features/installations/{installationId}/gateways/{gatewaySerial}/devices/{deviceId}/features` → `{data[]}` | [FAKT 2026-09-03] |
| Pojedyncza cecha | `GET …/features/{featureName}` — każda cecha ma własne pole `uri` w tym formacie | [FAKT 2026-09-03] |
| Nieistniejąca cecha | `404 {"errorType":"FEATURE_NOT_FOUND","message":"Feature not found","extendedPayload":{}}` | [FAKT 2026-09-03] |
| Zły/wygasły token | `401 {"errorType":"UNAUTHORIZED","message":"Request contain invalid token","error":"NO TOKEN AVAILABLE"}` | [FAKT 2026-09-03] |
| Wykonanie komendy | `POST …/features/{featureName}/commands/{commandName}` z JSON params | [FAKT — `uri` komendy jest zwracane w cesze; używać **zwróconego `uri`**, nie budować ręcznie] |
| Cechy bramki | `GET /features/installations/{id}/gateways/{serial}/features` → `gateway.devices`, `gateway.wifi` | [FAKT 2026-09-03] |

Nagłówek: `Authorization: Bearer {access_token}`.

Odpowiedź listy instalacji **[FAKT 2026-09-03]**:
```
data[].id (int)                    → installationId
data[].description, address{street,houseNumber,zip,city,country,geolocation{latitude,longitude,timeZone}},
       aggregatedStatus, heatingType, installationType, accessLevel, ownershipType, brand   ← PII (w fixtures zanonimizowane)
data[].gateways[].serial (16 cyfr) → gatewaySerial; version, gatewayType ("TCU200"), aggregatedStatus, otaOngoing
data[].gateways[].devices[].id     → deviceId: "0" (kocioł), "gateway" (TCU), "RoomControl-1"
data[].gateways[].devices[].modelId ("E3_Vitodens_200_0421"), deviceType ("heating" | "tcu" | "roomControl"),
       status ("Online"), roles[] (np. "type:boiler", "type:product;Vitodens_200", "interface:domesticHotWater",
       "interface:solar", "capability:consumptionReport;thermal")
```
`id == "gateway"` to sama bramka (1 cecha `tcu.features.wirelessRemoteController`); RoomControl ma 363 cechy
boolean/array (pokoje). Oba zachować w discovery, domyślnie nie dodawać jako urządzenia użytkownika.
`roles` to gotowe źródło typu urządzenia (`type:boiler`, `type:heatpump`…) — używać w discovery.

## 4. Format cechy (feature) — [FAKT 2026-09-03, zrzut Vitodens 200 E3]

Pola elementu `data[]`: `feature`, `gatewayId`, `deviceId`, `timestamp`, `isEnabled`, `isReady`, `apiVersion` (=1),
`uri`, `properties`, `commands`, opcjonalnie `deprecated` (4 cechy) i `components`. Realne komendy:
`heating.circuits.0.operating.programs.normal` → `setTemperature {targetTemperature: number, min 3, max 37, stepping 1}`;
`heating.dhw.temperature.main` → `setTargetTemperature {temperature: number, min 10, max 60, stepping 1,
efficientLowerBorder/efficientUpperBorder}` — **nazwa parametru ≠ nazwa property** (`14-open-questions.md`).
Starszy przykład (Vitodens 200-W, 2021) poniżej pozostaje strukturalnie aktualny:

```json
{
  "feature": "heating.circuits.0.heating.curve",
  "isEnabled": true,
  "isReady": true,
  "properties": {
    "shift": { "type": "number", "unit": "", "value": 4 },
    "slope": { "type": "number", "unit": "", "value": 1.2 }
  },
  "commands": {
    "setCurve": {
      "isExecutable": true,
      "name": "setCurve",
      "params": {
        "shift": { "type": "number", "required": true, "constraints": { "min": -13, "max": 40, "stepping": 1 } },
        "slope": { "type": "number", "required": true, "constraints": { "min": 0.2, "max": 3.5, "stepping": 0.1 } }
      },
      "uri": "https://api.viessmann-climatesolutions.com/iot/v1/features/installations/.../features/heating.circuits.0.heating.curve/commands/setCurve"
    }
  },
  "components": [],
  "timestamp": "2021-09-03T17:11:03.506Z"
}
```

Zaobserwowane typy `properties.*.type` [FAKT 2026-09-03]: `number` (166), `string` (79), `boolean` (27),
`array` (31), `Schedule` (2) na kotle; RoomControl: `boolean`, `array`.
Zaobserwowane jednostki [FAKT 2026-09-03]: `celsius`, `percent`, `kilowattHour`, `kilowattHour/year`, `cubicMeter`,
`hour`, `minute`, `liter`, `bar`, `kelvin`, `meter`, `degree`, `""` oraz brak pola `unit` (115 właściwości) —
parser akceptuje **dowolny** string jednostki i jej brak.

Zaobserwowane komendy [FAKT 2026-09-03] (33 wykonywalne na kotle): `activate`, `deactivate`, `setActive`,
`setName`, `setCurve`, `setSchedule`, `resetSchedule`, `resetDay`, `setMode`, `setTemperature`,
`setTargetTemperature`, `setMin`, `setMax`, `setLevels`, `enable`, `disable`, `setEnabled`, `triggerOncePerWeek`,
`triggerDaily`, `setHysteresis`, `setHysteresisSwitchOnValue`, `setHysteresisSwitchOffValue`, `changeEndDate`,
`schedule`, `unschedule`. `Schedule` = `{mon..sun: [{mode, start, end, position}]}`.

Zaobserwowane rodzaje `constraints`: `min`, `max`, `stepping`, `enum` (lista), `maxLength`,
`efficientLowerBorder`/`efficientUpperBorder` (informacyjne), dla Schedule: `maxEntries`, `modes`,
`resolution`, `defaultMode`, `overlapAllowed`.

**Reguły dla parsera** (`apps/adapters/viessmann/parser.py`):
1. Nie zakładaj istnienia żadnej konkretnej cechy. Zapisuj wszystko, co przychodzi.
2. `isEnabled == false` → cecha zapisywana jako definicja z `is_enabled=false`, bez historii.
3. Komenda bez `isExecutable == true` **nie jest** komendą wykonywalną.
4. Wartości numeryczne → `value_num`; boolean → `value_bool`; string → `value_text`;
   array/Schedule/obiekt → `value_json`. Zapis do historii tylko dla num/bool/string
   (zmiana wartości) — JSON tylko do „ostatniej wartości” i przy zmianie hash-u.
5. `timestamp` cechy ≠ czas odczytu; zapisywać oba (`ts_device`, `ts_polled`).

## 5. Limity wywołań

| Co | Wartość | Status |
|---|---|---|
| Plan Basic | **1450 wywołań / 24 h**, okno przesuwne, po przekroczeniu blokada do końca okna | [FAKT — FAQ Viessmann, 04/2026] |
| Limit krótki | 120 / 10 min | [podaje HA; brak w FAQ Viessmann — traktować jako obowiązujący, bo koszt błędu jest wysoki] |
| Plany płatne Advanced | **wycofane**; dla firm „custom solutions” — kontakt developer@viessmann-climatesolutions.com | [FAKT — Pricing] |
| Zakres limitu: per konto użytkownika czy per Client ID | **NIEZNANY** | [ZAŁOŻENIE robocze: per konto użytkownika; FAQ mówi o „user requests”] |

**Konsekwencje** (patrz `06-polling-and-budget.md`): budżet liczony i egzekwowany w bazie per
`provider_account`; rezerwa 15 % na komendy i odświeżenia na żądanie; przy 6 urządzeniach ≈ 1 odczyt
urządzenia co ~7 min.

**Test w etapie 0 (warunek kontynuacji):** dwa konta Viessmann, jeden Client ID; wyczerpać limit
na koncie A; sprawdzić, czy konto B nadal odpowiada. Jeśli nie → limit jest per Client ID → projekt
przy 500 urządzeniach wymaga umowy z Viessmann.

## 6. Błędy i zachowania

| Sygnał | Znaczenie | Obsługa w Termolink |
|---|---|---|
| HTTP 400/404, `errorType: DEVICE_COMMUNICATION_ERROR`, `extendedPayload.reason: GATEWAY_OFFLINE` | bramka bez łączności [FAKT — HA] | status urządzenia `offline`, nie jest błędem portalu; alert po N min |
| `errorType: ENDPOINT_NOT_FOUND` [FAKT — PyViCare] | endpoint nie istnieje | log + alert operatora „możliwa zmiana API” |
| HTTP 429 lub błąd z treścią o limicie [ZAŁOŻENIE: 429] | limit wyczerpany | status konta `rate_limited` do `budget_reset_at`; wstrzymać odczyty |
| HTTP 401 | token wygasł | odśwież i ponów raz; jeśli nadal 401 → `reauth_required` |
| Komenda → 404 mimo `isExecutable` [FAKT — HA issue #103008] | model nie wspiera komendy | zapisz w audicie, oznacz komendę jako `unsupported` dla tego urządzenia, ukryj kontrolkę |
| Brak części wartości znanych z ViCare [FAKT — PyViCare README] | API nie udostępnia wszystkiego | nie obiecywać; grupa „pozostałe” pokazuje wszystko, co jest |

## 7. Typy urządzeń (wg PyViCare/HA) — [FAKT]

Kotły gazowe, olejowe, pellet, pompy ciepła, hybrydy, ogniwa paliwowe, wentylacja.
Komponenty: `heating.circuits.N`, `heating.burners.N`, `heating.compressors.N`, `heating.dhw`,
`heating.solar`, `heating.boiler`, `heating.sensors`, `device.*`, `ventilation.*` [ZAŁOŻENIE dla
wentylacji i buforów].

## 8. Zmienność API (historia)

- 2021: wyłączenie starego endpointu `/general-management` na rzecz `/iot/v1`; zmiana domen
  (`api.viessmann.com` → `api.viessmann-platform.io` → `api.viessmann-climatesolutions.com`).
- Wniosek: base URL, auth URL i ścieżki **w konfiguracji**, nie w kodzie; monitoring
  „0 udanych odczytów w 60 min” → alert; śledzić changelog Viessmann i repozytorium PyViCare.

## 9. Lista rzeczy do sprawdzenia w portalu deweloperskim (etap 0)

- [x] Dokładne base URL i ścieżki features/commands — `/iot/v2` (2026-09-03).
- [x] Czas życia access tokena (3600 s); refresh token nie rotuje. [ ] Czas życia refresh tokena — obserwować.
- [ ] Zakres limitu (per konto vs per Client ID) — test z dwoma kontami.
- [ ] Kod HTTP i format odpowiedzi przy przekroczeniu limitu.
- [ ] Czy istnieje limit 120/10 min.
- [x] Zrzuty `…/features` dla pierwszej instalacji (kocioł + bramka + RoomControl) → fixtures. [ ] Pozostałe instalacje klienta.
- [x] Komendy `isExecutable` — lista w §4.
- [x] Cechy zużycia: kocioł zwraca `kilowattHour` (36 właściwości) i `cubicMeter` (24) — grupa `statistics`.
- [ ] Sekcja EU Data Act w portalu — czy daje dodatkowe dane.
