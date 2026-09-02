# 02 — Architektura

## Widok ogólny

```
                    ┌────────────────────────── VPS (Docker Compose) ───────────────────────────┐
 Przeglądarka ────▶ │ caddy  (TLS, HSTS, rate-limit, static frontend, reverse proxy → backend)   │
                    │   │                                                                        │
                    │   ▼                                                                        │
                    │ backend  (Django + DRF, gunicorn; bezstanowy; sesje w DB)                   │
                    │   │  ▲                                                                     │
                    │   ▼  │ tylko odczyt/zapis w DB                                             │
                    │ db  (PostgreSQL 16 + TimescaleDB; RLS; kolejka zadań; sesje)  ◀──┐         │
                    │                                                                  │         │
                    │ worker  (Django management command, asyncio + httpx)  ───────────┘         │
                    │   ├─ scheduler: kolejkuje odczyty wg budżetu per provider_account           │
                    │   ├─ poller: wykonuje odczyty równolegle, zapisuje cechy/historię           │
                    │   ├─ commander: wykonuje zatwierdzone komendy + weryfikacja                 │
                    │   ├─ alerts: reguły offline / zakres / komunikaty                           │
                    │   └─ reports: PDF/CSV, wysyłki e-mail                                       │
                    │                                                                            │
                    │ adapters/  viessmann | <następny producent>  (ten sam interfejs)            │
                    └────────────────────────────────────┬───────────────────────────────────────┘
                                                         ▼
                                  api.viessmann-climatesolutions.com / iam.viessmann-climatesolutions.com
```

## Zasady

1. **Monolit modularny.** Jeden projekt Django, moduły jako aplikacje Django z jawnymi interfejsami
   (funkcje serwisowe w `services.py`), bez wywołań między modelami innych modułów „na skróty”.
2. **Worker ≠ web.** Web nigdy nie woła API producenta synchronicznie. Wyjątki (jawne, zużywają
   budżet): „Odśwież teraz” i wykonanie komendy — oba trafiają do kolejki zadań, a UI odpytuje status
   zadania (polling co 1–2 s przez ~60 s).
3. **Bezstanowy backend.** Sesje w DB (`django.contrib.sessions` z backendem DB), brak stanu w
   pamięci procesu, więc `backend` i `worker` mogą mieć wiele replik.
4. **Kolejka zadań w DB.** Tabela `jobs` + `SELECT … FOR UPDATE SKIP LOCKED`. Bez Redis/Celery w v1.
   Jeśli kiedyś potrzebne — wymiana w jednym module `apps/ingest/queue.py`.
5. **Adaptery.** Wszystko specyficzne dla producenta żyje w `apps/adapters/<provider>/`. Reszta
   systemu zna wyłącznie znormalizowany model z `05-adapter-interface.md`.
6. **Konfiguracja przez zmienne środowiskowe** (12-factor). Base URL-e API producenta w konfiguracji.

## Przepływy

### A. Podłączenie konta Viessmann (wykonuje operator przy wdrożeniu)
1. Operator w panelu klienta → „Podłącz konto Viessmann” → backend tworzy `oauth_states`
   (state, code_verifier, tenant_id, user_id, expires) → redirect do IdP.
2. Klient loguje się swoim kontem ViCare w oknie Viessmann.
3. Callback → backend weryfikuje `state`, wymienia kod → zapisuje `provider_account`
   (refresh token zaszyfrowany) → kolejkuje job `discover`.
4. Worker: `discover` → zapisuje `discovered_devices` (cache drzewa instalacji).
5. Operator w kreatorze wybiera urządzenia → tworzy `devices` (nazwa, lokalizacja, opis, tryb)
   → job `poll` natychmiast.

### B. Cykliczny odczyt
Scheduler co 10 s: dla każdego `provider_account` z `status='active'` liczy dostępny budżet
(`06-polling-and-budget.md`), wybiera urządzenia z najstarszym `next_poll_at <= now()`, tworzy joby
`poll(device_id)`. Poller wykonuje: GET features → parser → upsert `feature_definitions`,
upsert `feature_latest`, insert `feature_values` (tylko zmienione wartości lub co najmniej raz na
cykl dla numerycznych — patrz `03-data-model.md`), aktualizuje `devices.status`, `last_seen_at`,
`next_poll_at`, zwiększa licznik budżetu.

### C. Sterowanie
Patrz `07-control-flow.md`. Skrót: UI → `POST /control/commands` (draft) → potwierdzenie →
`POST /control/commands/{id}/confirm` → job `execute_command` → adapter → wynik → job
`verify_command` po 60 s → audit.

### D. Raport
UI → `POST /reports/jobs` → job `render_report` → plik w `media/reports/{tenant}/…` → UI pobiera.
Cykliczne: scheduler tworzy joby wg `report_schedules.cron`.

## Skalowanie do 100 klientów / 500 urządzeń

| Obszar | Decyzja od v1 |
|---|---|
| Odczyty | asyncio + httpx, do 20 równoległych żądań na worker; wiele workerów przez `SKIP LOCKED` |
| Budżet | licznik w DB per provider_account, transakcyjny; nigdy w pamięci |
| Historia | hypertable Timescale, kompresja po 7 dniach, continuous aggregates 1 h / 1 d |
| Izolacja | `tenant_id` + RLS od pierwszej migracji |
| DB | osobny kontener, `DATABASE_URL` — przenośna na osobny host bez zmian kodu |
| Web | bezstanowy, N replik za Caddy |
| Zadania długie | zawsze przez `jobs`, nigdy w żądaniu HTTP |

Nie robimy w v1: mikroserwisów, Kubernetes, shardingu, osobnej bazy szeregów.

## Nazewnictwo i konwencje kodu

- Python: `ruff` (format + lint), `mypy --strict` dla `apps/adapters` i `apps/control`, `pytest`.
- Django apps w `apps/`, każdy z: `models.py`, `services.py` (logika), `api.py` (DRF views/serializers),
  `tests/`. Widoki nie zawierają logiki biznesowej — wołają `services`.
- Identyfikatory zewnętrzne: UUID v4. Klucze wewnętrzne: `bigint` tylko w tabelach historii.
- Czas: zawsze UTC w DB (`timestamptz`); strefa użytkownika w UI (domyślnie `Europe/Warsaw`).
- Nazwy cech przechowywane dokładnie jak w API (`feature_name`), bez normalizacji.
