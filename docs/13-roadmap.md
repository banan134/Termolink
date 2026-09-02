# 13 — Plan etapów i zadania

Każdy etap kończy się spełnieniem kryteriów „gotowe”. Zadania są w kolejności; Claude Code
powinien realizować je jako osobne, małe PR-y z testami.

## Etap 0 — Weryfikacja API (ręcznie, przed kodem) — WARUNEK KONTYNUACJI

- [ ] Client ID w portalu Viessmann z redirect URI dev i prod.
- [ ] Przebieg PKCE w Postmanie/httpie; zapis `expires_in`, sprawdzenie, czy refresh token rotuje.
- [ ] Zrzuty `GET /equipment/installations?includeGateways=true` oraz `…/features` dla **każdego z 6 urządzeń** → `backend/tests/fixtures/viessmann/<model>_<deviceId>.json` (zanonimizować numery seryjne).
- [ ] Zrzut odpowiedzi błędnej: bramka odłączona od zasilania (GATEWAY_OFFLINE); wygasły token (401).
- [ ] Test limitu: dwa konta Viessmann, jeden Client ID — wyczerpać limit na A, sprawdzić B. Zapisać
      kod HTTP i treść odpowiedzi przy limicie.
- [ ] Lista komend `isExecutable=true` per urządzenie; próba wykonania jednej nieszkodliwej (np. `setName`
      na wartość identyczną) — zapis odpowiedzi.
- [ ] Sprawdzenie sekcji EU Data Act i zakresu planu Basic.
- [ ] Uzupełnienie `01-viessmann-api.md` — zamiana [ZAŁOŻENIE] na [FAKT] lub korekta.

**Gotowe:** fixtures dla 6 urządzeń w repo; znany zakres limitu; znany czas życia tokenów; sekcja 9
w `01-viessmann-api.md` odhaczona.

## Etap 1 — Fundament

- [ ] Repo na GitHub, `deploy/docker-compose.yml` + nakładki dev/prod, Makefile, Django 5 + DRF + drf-spectacular, Postgres + Timescale (healthcheck), Mailpit w dev, ruff/mypy, CI. **Kryterium: `make dev` na czystym komputerze z samym Dockerem stawia działającą aplikację na http://localhost:8080.**
- [ ] Modele: tenants, users, memberships, invitations; role; Argon2; sesje DB; CSRF.
- [ ] `TenantContextMiddleware` + RLS (migracje `RunSQL`) na wszystkich tabelach z `tenant_id`.
- [ ] Auth API: login (z blokadą), logout, me, reset, zaproszenia, TOTP (setup/enable/disable), reauth, sesje.
- [ ] `audit_log` append-only + helper `audit(action, target, details)`.
- [ ] Kolejka `jobs` + `run_worker` (pusty worker z heartbeat).
- [ ] Frontend: Vite + React + TS, tokeny CSS, layout, logowanie, `/account`, generowanie typów z OpenAPI.
- [ ] Testy izolacji (parametryczne) i auth.

**Gotowe:** test izolacji zielony dla wszystkich istniejących endpointów; logowanie z 2FA działa w UI.

## Etap 2 — Adapter Viessmann i odczyt

- [ ] `adapters/base.py`, rejestr, `adapters/viessmann/` (client, auth, parser, errors) + testy na fixtures; tryb `VIESSMANN_MOCK=1` czytający fixtures.
- [ ] `provider_accounts`, szyfrowanie tokenów (`crypto.py`), OAuth start/callback, discover, `discovered_devices`.
- [ ] `devices`, `feature_definitions`, `feature_latest`, `feature_values` (hypertable, kompresja), agregaty 1h/1d, `grouping.py`.
- [ ] Budżet (`budget.py`) + testy współbieżności; scheduler; poller; statusy; `api_calls`.
- [ ] API: provider-accounts, devices (CRUD operatora), features, history, status-history, refresh.
- [ ] Frontend: panel operatora (klienci, konto Viessmann, kreator dodawania urządzenia z trybem).

**Gotowe:** urządzenie testowe widoczne, historia rośnie zgodnie z budżetem, po odłączeniu bramki
status offline w ≤ 2 cykle, budżet nigdy nie przekroczony (test 24 h na staging z logiem `api_calls`).

## Etap 3 — Dashboardy

- [ ] Słownik `feature_labels` + panel operatora do edycji + import startowy (CSV w repo, uzupełniany z fixtures).
- [ ] Dashboard klienta (karty, highlights, budżet, zdarzenia), karta urządzenia (Przegląd/Wykresy/Wszystkie cechy/Komunikaty), widgety per typ, tabela „pozostałe”.
- [ ] Wykresy z auto-rozdzielczością; sparkline 24 h; `ChartExplorer` z drill-down, zakresami Dzień…Rok + własny, zoomem, porównaniem serii/okresów, statystykami, eksportem CSV, pobieraniem PNG z każdego wykresu (białe tło, stopka z zakresem i klientem) i stanem w URL (`09-frontend.md` §Wykresy); endpointy `history` rozszerzone o `gaps/stats/markers`, `history/multi`, `history.csv`.
- [ ] Ustawienia urządzenia (nazwa/lokalizacja/opis dla tenant_admin).
- [ ] Wydajność: skeletony, code-splitting, pomiar Web Vitals.

**Gotowe:** każda cecha z każdej fixture jest gdzieś widoczna; karta urządzenia < 500 ms przy ciepłym cache.

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
