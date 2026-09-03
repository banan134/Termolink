# 13 — Plan etapów i zadania

Każdy etap kończy się spełnieniem kryteriów „gotowe”. Zadania są w kolejności; Claude Code
powinien realizować je jako osobne, małe PR-y z testami.

## Etap 0 — Weryfikacja API (ręcznie, przed kodem) — WARUNEK KONTYNUACJI

Instrukcja i narzędzie: `16-etap-0-instrukcja.md` (`backend/scripts/viessmann_capture.py` robi PKCE,
zrzuty, anonimizację i raport; ręcznie zostaje portal deweloperski i decyzje o testach limitu/offline).

- [x] Client ID w portalu Viessmann z redirect URI dev (2026-09-03; prod do dodania przy wdrożeniu).
- [x] Przebieg PKCE (skrypt); `expires_in = 3600`, refresh token nie rotuje.
- [x] Zrzuty `installations` i `…/features` dla pierwszej instalacji (kocioł Vitodens 200 E3, bramka TCU200, RoomControl) →
      `backend/tests/fixtures/viessmann/` (zanonimizowane). [ ] Pozostałe urządzenia klienta (`--label` per instalacja).
- [ ] Zrzut odpowiedzi błędnej: bramka odłączona od zasilania (GATEWAY_OFFLINE); wygasły token (401).
- [ ] Test limitu: dwa konta Viessmann, jeden Client ID — wyczerpać limit na A, sprawdzić B. Zapisać
      kod HTTP i treść odpowiedzi przy limicie.
- [ ] Lista komend `isExecutable=true` per urządzenie; próba wykonania jednej nieszkodliwej (np. `setName`
      na wartość identyczną) — zapis odpowiedzi.
- [ ] Sprawdzenie sekcji EU Data Act i zakresu planu Basic.
- [x] Uzupełnienie `01-viessmann-api.md` — [FAKT 2026-09-03] (m.in. `/iot/v2`, v1 = 410 GONE). Otwarte: limit
      (A1/A3/A4), czas życia refresh tokena, bramka offline, komenda testowa.

**Gotowe:** fixtures dla 6 urządzeń w repo; znany zakres limitu; znany czas życia tokenów; sekcja 9
w `01-viessmann-api.md` odhaczona.

## Etap 1 — Fundament

- [x] Repo na GitHub, `deploy/docker-compose.yml` + nakładki dev/prod, Makefile, Django 5 + DRF + drf-spectacular, Postgres + Timescale (healthcheck), Mailpit w dev, ruff/mypy, CI. **Kryterium: `make dev` na czystym komputerze z samym Dockerem stawia działającą aplikację na http://localhost:8080.**
- [x] Modele: tenants, users, memberships, invitations; role; Argon2; sesje DB; CSRF.
- [x] `TenantContextMiddleware` + RLS (migracje `RunSQL`) na wszystkich tabelach z `tenant_id`.
- [x] Auth API: login (z blokadą), logout, me, reset, zaproszenia, TOTP (setup/enable/disable), reauth, sesje.
- [x] `audit_log` append-only + helper `audit(action, target, details)`.
- [x] Kolejka `jobs` + `run_worker` (pusty worker z heartbeat).
- [x] Frontend: Vite + React + TS, tokeny CSS, layout, logowanie, `/account`, generowanie typów z OpenAPI.
- [x] Testy izolacji (parametryczne) i auth; minimalne API operatora (`/admin/tenants*`, zaproszenia,
      przypisania serwisantów) i klienta (`/tenants/{tid}/users`) z ekranami w UI.

**Gotowe:** test izolacji zielony dla wszystkich istniejących endpointów; logowanie z 2FA działa w UI.

## Etap 2 — Adapter Viessmann i odczyt

- [x] `adapters/base.py`, rejestr, `adapters/viessmann/` (client, auth, parser, errors); tryb `VIESSMANN_MOCK=1`
      czytający fixtures. **Testy parsera na fixtures włączają się automatycznie po etapie 0** (do tego czasu pomijane).
- [x] `provider_accounts`, szyfrowanie tokenów (`core/crypto.py` + `providers/crypto.py`), OAuth start/callback, discover, `discovered_devices`.
- [x] `devices`, `feature_definitions`, `feature_latest`, `feature_values` (hypertable, kompresja; izolacja widokami
      `*_rls` — `03-data-model.md`), agregaty 1h/1d, `grouping.py`.
- [x] Budżet (`budget.py`) + testy współbieżności; scheduler; poller; statusy; `api_calls`.
- [x] API: provider-accounts, devices (CRUD operatora), features, history, status-history, refresh.
- [x] Frontend: panel operatora (konto Viessmann, wykrywanie, dodawanie urządzenia z trybem), karty urządzeń
      klienta (`/t/:tid`), karta urządzenia (tabela cech, prosty wykres SVG — ECharts w etapie 3).
- [ ] **Weryfikacja na prawdziwym urządzeniu (wymaga etapu 0)**: parser na fixtures, 24 h na staging z logiem `api_calls`.

**Gotowe:** urządzenie testowe widoczne, historia rośnie zgodnie z budżetem, po odłączeniu bramki
status offline w ≤ 2 cykle, budżet nigdy nie przekroczony (test 24 h na staging z logiem `api_calls`).

## Etap 3 — Dashboardy

- [x] Słownik `feature_labels` + panel operatora do edycji (`/admin/labels`) + import startowy (CSV w repo, uzupełniony z fixtures).
- [x] Dashboard klienta (karty, highlights ze słownika), karta urządzenia (Przegląd/Wykresy/Wszystkie cechy/Komunikaty), widgety per typ (number+sparkline, boolean, string, schedule, JSON), tabela „pozostałe”. [ ] Budżet i ostatnie zdarzenia na dashboardzie klienta.
- [x] Wykresy z auto-rozdzielczością; sparkline 24 h; `ChartExplorer` (ECharts) z drill-down, zakresami Dzień…Rok + własny, zoomem (dataZoom → zawężenie zakresu i przejście na surowe ≤ 48 h), porównaniem serii (≤ 6, druga oś Y dla innej jednostki) i okresów, statystykami, eksportem CSV, PNG (białe tło, stopka) i stanem w URL; endpointy `history` rozszerzone o `gaps/stats/markers`, `history/multi`, `history.csv`.
- [x] Ustawienia urządzenia (nazwa/lokalizacja/opis dla tenant_admin; tryb z reauth, interwał, limit komend dla operatora).
- [x] Wydajność: skeletony, code-splitting per ekran. [ ] Pomiar Web Vitals (`/metrics/web-vitals`).

**Gotowe:** każda cecha z każdej fixture jest gdzieś widoczna; karta urządzenia < 500 ms przy ciepłym cache.
[ ] Pomiar czasu karty urządzenia na staging.

## Etap 4 — Sterowanie

- [ ] `control/`: `can_control`, walidacja constraints, maszyna stanów `commands`, joby execute/verify, allowlist, `unsupported_commands`, limit/h, komendy wrażliwe.
- [ ] API commands + dziennik zmian; PATCH `mode` z reauth (operator).
- [ ] Frontend: kontrolki per typ, `ConfirmDialog` (odliczanie, checkbox), `ReauthDialog`, polling statusu, `ScheduleEditor` (prosty).
- [ ] Testy obowiązkowe z `07-control-flow.md`.

**Gotowe:** komenda w trybie `read` odrzucona serwerowo; tenant_user 403; zmiana temperatury na
urządzeniu testowym w stanie `verified`; `verify_mismatch` odtworzony w teście.

## Etap 5 — Raporty i alarmy

- [ ] Preview, CSV, PDF (WeasyPrint, logo warunkowo), `report_files`, harmonogramy, e-mail.
- [ ] Alarmy: reguły, otwieranie/zamykanie, deduplikacja, e-mail, UI.
- [ ] Frontend: raporty, harmonogramy, alarmy, reguły.

**Gotowe:** raport miesięczny dla urządzenia testowego zgodny z danymi z bazy (test porównawczy);
alarm offline przychodzi e-mailem po 30 min.

## Etap 6 — Utwardzenie i wdrożenie produkcyjne

- [ ] CSP bez `unsafe-inline`, rate limiting, nagłówki, sanitizacja SVG.
- [ ] Backup + test odtworzenia; monitoring; runbook operatora (`ops/runbook.md`: reauth klienta, rotacja klucza, przywracanie, dodanie serwisanta).
- [ ] Test penetracyjny (zewnętrzny) i usunięcie ustaleń krytycznych/wysokich.
- [ ] Weryfikacja palety z księgą znaku Wodmiar (jeśli istnieje); audyt kontrastu.
- [ ] Wdrożenie pierwszego klienta (6 urządzeń) w trybie `read`; po 2 tygodniach obserwacji —
      włączenie `control` na wybranych urządzeniach.

**Gotowe:** raport pentestu bez krytycznych/wysokich; odtworzenie z backupu udokumentowane; klient produkcyjny działa ≥ 14 dni bez interwencji.

## Po v1 (kandydaci)

Automatyzacje/reguły; drugi producent przez adapter; powiadomienia push; aplikacja mobilna (PWA
w pierwszej kolejności); porównania między urządzeniami klienta; eksport do systemów rozliczeń
(Wodmiar zajmuje się rozliczaniem wody i ciepła — potencjalna synergia, poza zakresem v1).
