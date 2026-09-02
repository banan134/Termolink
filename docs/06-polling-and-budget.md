# 06 — Odpytywanie i budżet API

## Budżet (per `provider_account`)

Definicje:
- `limit` = 1450, `window_s` = 86400 (okno przesuwne — liczymy z `api_calls` gdzie `ts > now() - window`).
- `reserve` = `limit × budget_reserve_pct / 100` (domyślnie 15 % ≈ 217) — tylko na komendy,
  weryfikację po komendzie, „Odśwież teraz”, discover, odświeżenie tokena.
- `poll_budget` = `limit − reserve` (≈ 1233).
- `short_limit` = 120 / 600 s — twardy hamulec: nigdy więcej niż 110 wywołań w 10 min (margines).

Funkcje (`apps/providers/budget.py`), wszystkie transakcyjne w DB:
```
used(account, window) -> int
available_for_poll(account) -> int      # poll_budget - used_by_polls
available_for_reserve(account) -> int   # reserve - used_by_reserve_kinds
try_acquire(account_id, kind, device_id=None) -> ApiCall | None   # SELECT ... FOR UPDATE na provider_accounts; INSERT api_calls; sprawdza oba okna
finish_call(call, http_status, duration_ms, error_type)              # uzupełnia wpis po wywołaniu
status(account) -> BudgetStatus                                      # used/limit/reset_at + podział poll/reserve/short
```
`try_acquire` jest **jedynym** miejscem, w którym powstaje wpis `api_calls` przed wywołaniem; po
wywołaniu wpis jest uzupełniany (`http_status`, `duration_ms`, `error_type`).

## Interwał odczytu

Dla konta z `n` aktywnych urządzeń (status ≠ archived, konto active):

```
auto_interval_s = ceil(window_s / (poll_budget / n))           # przy n=6: 86400 / 205.5 ≈ 420 s ≈ 7 min
interval(device) = max(device.poll_interval_s or auto_interval_s, 60, short_floor)
short_floor = ceil(short_window_s / (short_limit*0.9) * n)     # n=6: 600/108*6 ≈ 33 s → nieistotne
```
Jeśli suma ręcznie ustawionych interwałów przekracza budżet → scheduler wydłuża je proporcjonalnie
i oznacza konto `budget_overcommitted=true` (widoczne operatorowi). Nigdy nie przekraczamy limitu.

## Scheduler (`apps/ingest/scheduler.py`, tick co 10 s)

```
for account in provider_accounts where status='active':
    n = count active devices
    for device in devices where next_poll_at <= now() order by next_poll_at:
        if not budget.available_for_poll(account) > 0: break
        enqueue job('poll', device_id, priority=100, run_at=now)
        device.next_poll_at = now + interval(device)      # ustawiane od razu, żeby nie zdublować
```
Rozkład startowy: przy dodaniu urządzeń `next_poll_at` przesunięte o `interval / n × i`, żeby
odczyty były równomierne, a nie w paczkach.

## Poller (`apps/ingest/poller.py`)

```
job poll(device):
  account = device.provider_account
  if not budget.try_acquire(account, 'poll'): reschedule(+60s); return
  tokens = ensure_fresh_tokens(account)      # odświeżenie liczone jako 'refresh_token' z rezerwy
  try:
      features = adapter.read_features(tokens, descriptor)
  except DeviceOfflineError: set_status(device,'offline'); return
  except AuthError: account.status='reauth_required'; alert(operator); return
  except RateLimitedError as e: account.status='rate_limited'; account.status_until = ...; pause all polls; return
  except TransientError: retry with backoff (1, 5, 15 min; max 3) — ponowna próba też zużywa budżet
  ingest(features)                           # upsert definitions, latest, history (03-data-model.md)
  set_status(device,'online'); last_seen_at=now
```

Statusy urządzenia:

| Status | Warunek | Wyjście |
|---|---|---|
| `unknown` | nowe, brak odczytu | pierwszy wynik |
| `online` | ostatni odczyt OK | błąd offline / brak odczytu > 3×interval |
| `offline` | `DeviceOfflineError` lub brak udanego odczytu > 3×interval | udany odczyt |
| `error` | inny błąd API 3× z rzędu | udany odczyt |
| `rate_limited` | konto w `rate_limited` | reset okna |

Każda zmiana → `device_status_history` + ewentualny alert (`device_offline` po `minutes` z reguły).

## „Odśwież teraz” i komendy

Używają `try_acquire(account, 'refresh'|'command'|'verify')` z rezerwy. Gdy rezerwa wyczerpana →
HTTP 429 z `retry_at`. Rezerwa chroni sterowanie przed zagłodzeniem przez odczyty i odwrotnie.

## Wiele workerów

Job pobierany przez `UPDATE jobs SET locked_by, locked_at WHERE id = (SELECT id … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`.
Job zablokowany > 10 min bez zakończenia → uznany za porzucony (worker padł) → odblokowany.
Heartbeat workerów w tabeli `worker_heartbeats` (upsert co tick, `03-data-model.md`); brak heartbeatu > 2 min → alert operatora.
Handlery jobów rejestrowane dekoratorem `ingest.queue.job_handler(kind)`; każdy job wykonuje się w osobnej transakcji
z kontekstem RLS `system` zawężonym do `tenant_id` joba.

## Metryki (endpoint `/admin/system/health` + logi)

Wywołania/h per konto, błędy per typ, średni czas odpowiedzi API, zaległość jobów, wiek najstarszego
`next_poll_at` przeterminowanego, liczba urządzeń per status.
