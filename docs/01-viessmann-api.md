# 01 — API Viessmann: fakty, założenia, do weryfikacji

> **Status źródeł.** Oficjalna dokumentacja (https://api.viessmann-climatesolutions.com/documentation)
> jest aplikacją JS i nie została odczytana automatycznie. Poniższe informacje pochodzą z:
> FAQ i cennika portalu deweloperskiego Viessmann, dokumentacji integracji `vicare` w Home Assistant,
> README oraz danych testowych biblioteki PyViCare (github.com/openviess/PyViCare).
> Oznaczenia: **[FAKT]** — potwierdzone w źródle; **[ZAŁOŻENIE]** — do weryfikacji w etapie 0.
> **Nie implementuj niczego oznaczonego [ZAŁOŻENIE] jako pewnik — dodaj test na rzeczywistym zrzucie.**

## 1. Rejestracja klienta API

- **[FAKT]** Logowanie do portalu deweloperskiego tym samym kontem co aplikacja ViCare.
- **[FAKT]** W dashboardzie tworzy się „API client” z nazwą i **Redirect URI**; klient może być
  aktywny dopiero po ok. godzinie.
- **[FAKT]** Redirect URI musi dokładnie odpowiadać temu, którego używa aplikacja; niezgodność daje
  błąd „Invalid redirection URI”.
- Termolink używa: `https://<domena>/oauth/viessmann/callback` (produkcja) oraz
  `http://localhost:8000/oauth/viessmann/callback` (dev) — **oba muszą być wpisane w portalu Viessmann**.

## 2. Autoryzacja (OAuth2 Authorization Code + PKCE)

| Element | Wartość | Status |
|---|---|---|
| Authorization URL | `https://iam.viessmann-climatesolutions.com/idp/v3/authorize` | [FAKT] |
| Token URL | `https://iam.viessmann-climatesolutions.com/idp/v3/token` | [FAKT] |
| Scope | `IoT User` | [FAKT] |
| Client secret | brak (PKCE) | [FAKT] |
| PKCE | `code_challenge_method=S256` | [FAKT] |
| Czas życia access tokena | nieznany | [ZAŁOŻENIE: krótki, godziny] |
| Czas życia refresh tokena | **nieznany** — kluczowe dla UX, sprawdzić | [ZAŁOŻENIE] |
| Rotacja refresh tokena przy odświeżeniu | nieznana | [ZAŁOŻENIE: zapisywać nowy, jeśli zwrócony] |

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

Base URL: `https://api.viessmann-climatesolutions.com/iot/v1` **[FAKT — z README PyViCare; potwierdzić w docs]**

| Cel | Endpoint | Status |
|---|---|---|
| Lista instalacji z bramami i urządzeniami | `GET /equipment/installations?includeGateways=true` | [FAKT] |
| Wszystkie cechy urządzenia (1 wywołanie) | `GET /features/installations/{installationId}/gateways/{gatewaySerial}/devices/{deviceId}/features` | [FAKT] |
| Pojedyncza cecha | `GET …/features/{featureName}` | [ZAŁOŻENIE] |
| Wykonanie komendy | `POST …/features/{featureName}/commands/{commandName}` z JSON params | [FAKT — `uri` komendy jest zwracane w cesze; używać **zwróconego `uri`**, nie budować ręcznie] |
| Cechy bramki | `GET /features/installations/{id}/gateways/{serial}/features` | [ZAŁOŻENIE] |

Nagłówek: `Authorization: Bearer {access_token}`.

Odpowiedź listy instalacji (struktura wg PyViCare):
```
data[].id                          → installationId
data[].gateways[].serial           → gatewaySerial
data[].gateways[].devices[].id     → deviceId  (np. "0", "gateway", "HEMS")
data[].gateways[].devices[].modelId / deviceType / roles / status   [ZAŁOŻENIE: pola]
```
Urządzenie o `id == "gateway"` to sama bramka (w HA pomijane). Zachować w discovery, ale domyślnie
nie dodawać jako urządzenia użytkownika.

## 4. Format cechy (feature) — [FAKT, z rzeczywistego zrzutu Vitodens 200-W]

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

Zaobserwowane typy `properties.*.type`: `number`, `string`, `boolean`, `array`, `Schedule`.
Zaobserwowane jednostki: `celsius`, `percent`, `""`, oraz [ZAŁOŻENIE] `kilowattHour`, `cubicMeter`,
`hour`, `liter`, `bar`, `kelvin`, `watt` — parser musi akceptować **dowolny** string jednostki.

Zaobserwowane komendy: `setName` (string, maxLength 20), `setCurve`, `setSchedule`
(`Schedule` — `entries: [{start,end,mode,position}]` per dzień, `maxEntries`, `modes`,
`resolution`, `defaultMode`), `setMode` (`enum`), `setTemperature` (number, min/max/stepping),
`activate` / `deactivate` (bez parametrów).

Zaobserwowane rodzaje `constraints`: `min`, `max`, `stepping`, `enum` (lista), `maxLength`,
dla Schedule: `maxEntries`, `modes`, `resolution`, `defaultMode`, `overlapAllowed`.

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

- [ ] Dokładne base URL i ścieżki features/commands.
- [ ] Czas życia access/refresh tokena; czy refresh token rotuje.
- [ ] Zakres limitu (per konto vs per Client ID) — test z dwoma kontami.
- [ ] Kod HTTP i format odpowiedzi przy przekroczeniu limitu.
- [ ] Czy istnieje limit 120/10 min.
- [ ] Pełne zrzuty `…/features` dla **każdego** z 6 urządzeń klienta → `backend/tests/fixtures/viessmann/`.
- [ ] Które komendy są `isExecutable` na tych urządzeniach.
- [ ] Czy dostępne są cechy zużycia/energii (`heating.power.*`, `heating.gas.*`) dla tych modeli.
- [ ] Sekcja EU Data Act w portalu — czy daje dodatkowe dane.
