# 16 — Etap 0: instrukcja zrzutów z API Viessmann

Etap 0 (`13-roadmap.md`) to jedyna część projektu, której nie da się zrobić bez dostępu do konta
Viessmann. Skrypt `backend/scripts/viessmann_capture.py` wykonuje całą mechanikę (PKCE, pobranie
instalacji i cech, anonimizacja, raport) — ręcznie zostają tylko kroki w portalu deweloperskim.

## Krok 1 — Client ID (portal deweloperski Viessmann, ~15 min + do 1 h aktywacji)

1. Zaloguj się na https://app.developer.viessmann-climatesolutions.com tym samym kontem, co ViCare.
2. Utwórz „API client” o nazwie np. `Termolink dev` i **trzech** Redirect URI:
   - `http://localhost:8765/oauth/viessmann/callback` — używa go skrypt z etapu 0,
   - `http://localhost:8080/oauth/viessmann/callback` — środowisko dev (`15-local-development.md`),
   - `https://<docelowa domena>/oauth/viessmann/callback` — produkcja (można dodać później).
3. Zapisz Client ID w `deploy/.env` jako `VIESSMANN_CLIENT_ID`. Klient bywa aktywny dopiero po ok. godzinie.

## Krok 2 — zrzuty (na hoście, Python 3.12, bez Dockera)

```bash
python backend/scripts/viessmann_capture.py --client-id <CLIENT_ID> --label klient-1
```

Skrypt otworzy przeglądarkę; zaloguj się **kontem ViCare klienta** (tym, do którego przypisane są
urządzenia). Po powrocie na localhost skrypt pobierze:

| Plik w `backend/tests/fixtures/viessmann/` | Zawartość |
|---|---|
| `installations.json` | `GET /equipment/installations?includeGateways=true` |
| `features_<model>_<deviceId>.json` | pełna lista cech każdego urządzenia (1 wywołanie = 1 z budżetu) |
| `gateway_features.json` | cechy bramki (weryfikuje [ZAŁOŻENIE] z `01` §3) |
| `error_missing_feature.json` | odpowiedź na nieistniejącą cechę (kształt błędu) |
| `error_invalid_token.json` | odpowiedź 401 (do mapowania `AuthError`) |
| `capture_report.json` | `expires_in`, czy refresh token rotuje, kody HTTP, nagłówki rate-limit, czasy |
| `serial_mapping.json` | **lokalne** mapowanie prawdziwe → zanonimizowane numery (w `.gitignore`) |

Numery seryjne (16 cyfr) i identyfikatory instalacji są zastępowane placeholderami konsekwentnie we
wszystkich plikach, więc fixtures można commitować.

## Krok 3 — test limitu (opcjonalny, na koncie testowym, zużywa budżet)

```bash
python backend/scripts/viessmann_capture.py --client-id <CLIENT_ID> --label limit-test --probe-limit 200
```

Skrypt woła `/features` w pętli, aż dostanie błąd, i zapisuje go w `error_rate_limit.json` (kod HTTP,
treść, nagłówki `Retry-After`/`RateLimit-*`). Pytanie A1 z `14-open-questions.md` (limit per konto czy
per Client ID) sprawdza się, uruchamiając zaraz potem zwykły zrzut na **drugim** koncie z tym samym
Client ID: jeśli działa — limit jest per konto.

## Krok 4 — bramka offline (opcjonalny)

Odłącz bramkę od zasilania na kilka minut i uruchom zrzut z `--label gateway-offline --skip-refresh`.
Odpowiedź `/features` (oczekiwane `DEVICE_COMMUNICATION_ERROR` / `GATEWAY_OFFLINE`) trafi do
`features_*.json` ze statusem w `_meta.status`; przenieś ją ręcznie do `error_gateway_offline.json`.

## Krok 5 — przekazanie

Zacommituj katalog `backend/tests/fixtures/viessmann/` (bez `serial_mapping.json`) i podaj
w `capture_report.json` odpowiedzi na pytania A1–A8 z `14-open-questions.md`, jeśli je poznałeś.
Etap 2 startuje od parsera pisanego wyłącznie pod te pliki (`12-testing.md`).

## Co, jeśli…

| Objaw | Co zrobić |
|---|---|
| `Invalid redirection URI` | Redirect URI w portalu musi być **identyczny** znak w znak: `http://localhost:8765/oauth/viessmann/callback` (http, port 8765, bez ukośnika na końcu). Jeśli masz zarejestrowany inny lokalny adres, podaj go: `--redirect-uri http://localhost:8080/oauth/viessmann/callback` — skrypt nasłuchuje na porcie z tego adresu (zatrzymaj wtedy Caddy, jeśli używa tego portu). Zmiany w portalu mogą działać z opóźnieniem. |
| `invalid_client` | Client ID jeszcze nieaktywny (do 1 h) albo literówka |
| `installations` = 401 | token nie ma zakresu `IoT User` — sprawdź, czy klient ma włączone IoT |
| `410 GONE … Replacement: GET /iot/v2/…` | API v1 wyłączone (grudzień 2025); skrypt używa `/iot/v2` i sam podąża za zamiennikiem z odpowiedzi, zapisując to w `capture_report.json` → `deprecations` |
| brak `refresh_token` w odpowiedzi | zakres `offline_access` nie został przyznany; zapisz to w raporcie — wpływa na UX (`01` §2) |
