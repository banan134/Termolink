# 07 — Sterowanie urządzeniem

Zasada nadrzędna: **przypadkowa zmiana ma być praktycznie niemożliwa**, a każda świadoma zmiana
w pełni udokumentowana i zweryfikowana. Wszystkie reguły egzekwowane serwerowo; UI tylko je odzwierciedla.

## Tryby urządzenia

| `devices.mode` | Zachowanie |
|---|---|
| `read` (domyślny) | Tylko GET. Endpoint `POST …/commands` zwraca 403 `control_not_allowed` niezależnie od roli. UI nie renderuje kontrolek. |
| `control` | Kontrolki widoczne dla uprawnionych, tylko dla komend `executable=true` i nieobecnych w `unsupported_commands`. |

Zmianę trybu wykonuje wyłącznie operator (`superadmin`/`technician`), wymaga `reauth` (hasło + TOTP)
i tworzy wpis `audit_log(action='device.mode.changed')`.

## Kto może wykonać komendę — `control.services.can_control(user, device) -> (bool, reasons)`

Wszystkie warunki muszą być spełnione:
1. `device.mode == 'control'` (reason: `device_read_only`)
2. `device.tenant.control_allowed` (reason: `tenant_control_blocked`)
3. rola:
   - `superadmin` → OK (`acted_as_operator=true`)
   - `technician` → membership z `can_control` (`operator_no_control_permission`)
   - `tenant_admin` → `user.totp_enabled` (`totp_required`)
   - `tenant_user` → **zawsze false** (`role_not_allowed`)
4. `device.status in ('online',)` (reason: `device_not_online`) — nie wysyłamy komend do urządzeń offline
5. liczba komend `succeeded/verified` na tym urządzeniu w ostatniej godzinie < `commands_per_hour_limit` (`hourly_limit_reached`)
6. rezerwa budżetu ≥ 2 (komenda + weryfikacja) (`budget_reserve_exhausted`)

`GET /devices/{id}` zwraca `capabilities.can_control` + `reasons`, żeby UI pokazało właściwy komunikat.

## Komendy wrażliwe

Lista globalna w `settings.SENSITIVE_COMMANDS` (nadpisywalna przez operatora w `/admin/system`):
domyślnie `setMode`, `setSchedule`, `setCurve`, `deactivate`, każda komenda, której nazwa lub
`params.enum` zawiera `standby` / `off`. Komenda wrażliwa wymaga w kroku potwierdzenia ważnego
`reauth` (hasło + TOTP, ważność 5 min).

## Przebieg (maszyna stanów `commands.status`)

```
POST /devices/{id}/commands {feature_name, command_name, params}
  ├─ can_control? ✖ → 403
  ├─ feature_definitions: cecha istnieje, komenda executable, nie w unsupported → ✖ 422 command_not_available
  ├─ definicja starsza niż 30 min → wymuszony odczyt (rezerwa) → ponowna walidacja
  ├─ validate(params, constraints) ✖ → 422 constraint_violation {fields}
  ├─ value_before = feature_latest[...] (dla params mapowanych na properties o tej samej nazwie lub
  │                 mapowania z feature_labels.command_property_map [ZAŁOŻENIE: mapowanie ręczne])
  └─ INSERT commands(status='draft', sensitive, expires_at=now+5min) → 201 {id, value_before, value_after=params, sensitive, expires_at}

POST /commands/{id}/confirm {acknowledged:true}
  ├─ status=='draft' ∧ not expired ∧ ten sam user ✖ → 409
  ├─ sensitive ∧ session.reauth_until < now → 428 reauth_required
  ├─ can_control ponownie ✖ → 403 (warunki mogły się zmienić)
  └─ status='confirmed', confirmed_at; enqueue job execute_command(id, priority=10)

job execute_command:
  ├─ status=='confirmed' ✖ → skip
  ├─ budget.try_acquire('command') ✖ → reschedule +30 s (max 5 min, potem 'failed' budget)
  ├─ status='executing'; adapter.execute(...)
  ├─ ok → status='succeeded', api_status, executed_at; enqueue verify_command(run_at=+60s)
  ├─ CommandUnsupportedError → status='failed'; feature_definitions.unsupported_commands += cmd; alert operator
  └─ inne → status='failed', api_response

job verify_command:
  ├─ try_acquire('verify') → read_features → ingest
  ├─ porównaj value_after z feature_latest (z tolerancją stepping/2 dla number)
  ├─ zgodne → 'verified'; niezgodne → 'verify_mismatch' + alert dla użytkownika i operatora
  └─ (bez budżetu: ponów po 60 s, max 3; potem 'verify_pending' i wynik z kolejnego cyklicznego odczytu)
```

Każde przejście stanu → `audit_log`. `commands` jest widoczne w UI jako „Dziennik zmian”.

## Wymagania UI (kontrakt dla `09-frontend.md`)

1. Kontrolka nie wysyła nic sama — zmiana wartości aktywuje przycisk „Zastosuj zmianę…”.
2. Okno potwierdzenia pokazuje: urządzenie, lokalizację, cechę (etykieta PL + nazwa techniczna),
   „z X na Y” z jednostką, zakres z constraints, ostrzeżenie dla `sensitive`.
3. Checkbox odpowiedzialności + przycisk nieaktywny przez 3 s po otwarciu okna.
4. Dla `sensitive`: pole hasła + kod TOTP (wywołuje `/auth/reauth`) przed `confirm`.
5. Po `confirm` UI polluje `/commands/{id}` i pokazuje: wysłano → urządzenie potwierdziło (verified)
   / nie potwierdziło (verify_mismatch) / błąd (failed z treścią).
6. Komendy bez parametrów (`activate`) — ten sam przebieg, przycisk „Uruchom…”.
7. `setSchedule` — dedykowany edytor tygodniowy z walidacją identyczną jak serwerowa; v1 może być
   prosty (lista wpisów), ale musi respektować `maxEntries`, `modes`, `resolution`, `overlapAllowed`.

## Testy obowiązkowe (`12-testing.md`)

- tenant_user nigdy nie może utworzyć draftu (403) — dla obu trybów.
- tryb `read` → 403 dla superadmina.
- tenant_admin bez TOTP → 403 `totp_required`.
- `constraint_violation` dla każdej reguły z `05-adapter-interface.md`.
- wrażliwa bez reauth → 428; z reauth → OK.
- limit/h → 403 `hourly_limit_reached`.
- `verify_mismatch` gdy odczyt nie potwierdza.
- `CommandUnsupportedError` → `unsupported_commands` uzupełnione, kontrolka znika w `/features`.
