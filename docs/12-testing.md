# 12 — Testowanie

## Zasady

- Backend: `pytest` + `pytest-django` + `pytest-asyncio`; baza testowa PostgreSQL + Timescale
  (kontener w CI, **nie** SQLite — RLS i hypertable muszą być testowane naprawdę).
- Frontend: `vitest` + Testing Library; e2e: Playwright na staging (ścieżki krytyczne).
- Adaptery: **wyłącznie** na fixtures z rzeczywistych odpowiedzi API (`backend/tests/fixtures/viessmann/`),
  nagranych w etapie 0. Żadnych ręcznie wymyślonych struktur cech.
- HTTP do producenta w testach: `respx` (mock httpx). Zakaz realnych wywołań w testach.
- CI (GitHub Actions lub równoważne): lint → typy → testy → build obrazów. Merge tylko na zielono.

## Obowiązkowe zestawy testów

### Izolacja (`tests/test_isolation.py`) — generowany parametrycznie z listy endpointów
Dla każdego endpointu z `04-backend-api.md` z `{tid}` lub identyfikatorem zasobu:
1. użytkownik tenanta A → zasób tenanta B → **404**;
2. technician bez membership → 404; z membership → 200;
3. superadmin → 200;
4. zapytanie SQL bez `WHERE tenant_id` przez połączenie aplikacji z ustawionym kontekstem A →
   nie zwraca wierszy B (test RLS bezpośrednio na tabelach: devices, feature_latest, feature_values, commands, reports, alerts).

### Budżet (`tests/test_budget.py`)
- `try_acquire` odmawia po osiągnięciu `limit` w oknie przesuwnym i `short_limit` w krótkim oknie.
- Rezerwa: odczyty nie mogą zjeść rezerwy; komendy nie mogą zjeść puli odczytów.
- Współbieżność: 50 równoległych `try_acquire` przy 10 dostępnych → dokładnie 10 sukcesów (test na
  prawdziwym Postgresie z wątkami).
- `auto_interval` dla n = 1, 6, 50, 500.

### Parser Viessmann (`tests/adapters/test_viessmann_parser.py`)
- Każda fixture → liczba cech = liczba w JSON; wszystkie typy properties rozpoznane; komendy
  `isExecutable=false` nie są executable; `Schedule` → `schedule`; nieznana jednostka nie wysadza parsera.
- Snapshot test: `feature_definitions` z fixture nie zmienia się między uruchomieniami.

### Ingest (`tests/test_ingest.py`)
- Zmiana wartości → nowy wiersz historii; brak zmiany < 1 h → brak wiersza; brak zmiany > 1 h → wiersz.
- `feature_latest` zawsze aktualne. Agregaty 1h/1d odświeżają się (Timescale `refresh_continuous_aggregate` w teście).
- Statusy: offline po `DeviceOfflineError`; po 3×interval bez odczytu; online po sukcesie; `device_status_history` spójne.

### Sterowanie (`tests/control/`)
Pełna lista z `07-control-flow.md` §„Testy obowiązkowe” + walidacja constraints z
`05-adapter-interface.md` (każda reguła: przypadek OK i przypadek błędu).

### Auth (`tests/accounts/`)
- Argon2, blokada po 10 próbach, 2FA wymagane dla operatora, `reauth` wygasa po 5 min, zmiana hasła
  unieważnia inne sesje, zaproszenie jednorazowe i wygasające.

### Raporty (`tests/reports/`)
- Przyrost liczników z resetem; dostępność; CSV z BOM i `;`; PDF generuje się z logo i bez logo.

### E2E (Playwright, staging)
1. Logowanie z 2FA → dashboard → karta urządzenia → wykres.
2. Operator: podłączenie konta (mock IdP na staging) → discover → dodanie urządzenia w trybie `read`
   → brak kontrolek → zmiana trybu (reauth) → kontrolki widoczne.
3. tenant_admin: zmiana temperatury → dialog → odliczanie → checkbox → potwierdzenie → status „zweryfikowano”.
4. tenant_user: brak kontrolek; bezpośredni POST `/commands` → 403.

## Dane testowe

`manage.py seed_demo` tworzy: operatora i serwisanta (z TOTP), 2 klientów z administratorem
i użytkownikiem, po 2–3 urządzenia z fixtures, historię 30 dni (syntetyczną, oznaczoną jako demo —
etap 2) — tylko dla dev, blokada poza `DJANGO_ENV=dev`.

## Pokrycie

Minimum 85 % dla `apps/control`, `apps/providers/budget.py`, `apps/adapters`, `apps/tenants`.
Reszta: 70 %. Mierzone w CI (`coverage`).
