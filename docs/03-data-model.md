# 03 — Model danych

Konwencje: PK = `uuid` (poza historią), `created_at`/`updated_at timestamptz`, wszystkie tabele
z danymi klienta mają `tenant_id uuid NOT NULL` i politykę RLS. Migracje przez Django; DDL poniżej
jest wzorcem (Django ORM + `RunSQL` dla Timescale/RLS).

## Izolacja: Row-Level Security

```sql
-- na każdej tabeli z tenant_id:
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE devices FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON devices
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- rola operatora (superadmin/serwisant) używa osobnej polityki:
CREATE POLICY operator_access ON devices
  USING (current_setting('app.role', true) = 'operator'
         AND tenant_id = ANY (string_to_array(current_setting('app.allowed_tenants', true), ',')::uuid[]));
```

- Middleware `tenants.middleware.TenantContextMiddleware` otwiera transakcję per żądanie (zamiast
  `ATOMIC_REQUESTS`) i wykonuje w niej `set_config('app.tenant_id' | 'app.role' | 'app.allowed_tenants'
  | 'app.user_id', …, true)` (odpowiednik `SET LOCAL`). Najpierw ładuje użytkownika sesji w kontekście
  `system`, potem ustawia właściwy kontekst. Helpery: `tenants.context.set_context()` i
  `tenants.context.system_context()` (jedyny, jawny sposób obejścia izolacji — używany przez logowanie,
  worker-scheduler i `seed_demo`; wywołania łatwo znaleźć grepem).
- Role DB: **`termolink`** (właściciel, tylko migracje: `DJANGO_DB_ROLE=admin`) i **`termolink_app`**
  (`LOGIN NOBYPASSRLS`, aplikacja i worker; domyślne `DJANGO_DB_ROLE=app`). Rola `termolink_app` jest
  tworzona migracją (`tenants.0002`) z hasłem z `DB_APP_PASSWORD`, z `GRANT` na istniejące tabele
  i `ALTER DEFAULT PRIVILEGES` na przyszłe. Bez tego rozdziału RLS nie działa — superuser omija RLS
  niezależnie od `FORCE`. Worker ustawia kontekst jawnie per job (etap 1, zadanie 8).
- Wartości `app.role`: `tenant` (użytkownik klienta), `operator` (superadmin/serwisant),
  `system` (wewnętrzne), `anonymous` (brak sesji). Superadmin: `app.allowed_tenants` = wszystkie
  tenanty (odświeżane per request); serwisant: tenanty z `tenant_memberships`.
- Polityki (helper `tenants.rls.rls_operations(table, tenant_nullable)` dla migracji `RunSQL`):
  `tenant_isolation` (jak wyżej, z `NULLIF(…, '')` dla pustego kontekstu), `operator_access`,
  `system_access` (`app.role = 'system'`) oraz — dla tabel z `tenant_id NULL` (`users`, `invitations`) —
  `operator_global_rows` (`app.role = 'operator' AND tenant_id IS NULL`), żeby operator widział konta
  operatorów. Test w `apps/tenants/tests/test_rls.py` przełącza się na `termolink_app` (`SET LOCAL ROLE`).

## Tabele

### Konta i klienci

```sql
tenants (
  id uuid PK, name text, type text CHECK (type IN ('company','person')),
  control_allowed boolean DEFAULT true,       -- operator może globalnie zablokować sterowanie
  logo_path text NULL, report_header_text text NULL,
  timezone text DEFAULT 'Europe/Warsaw', created_at, updated_at, archived_at NULL)

users (
  id uuid PK, tenant_id uuid NULL REFERENCES tenants,   -- NULL = operator
  email text, password_hash text,             -- unikalność: UNIQUE (lower(email)); Django 5.1 nie ma już citext
  role text CHECK (role IN ('superadmin','technician','tenant_admin','tenant_user')),
  totp_secret_enc bytea NULL, totp_enabled boolean DEFAULT false,
  backup_codes_hash text[] NULL, is_active boolean, ui_theme text DEFAULT 'light',
  last_login_at, created_at)
  -- reguła: role IN ('superadmin','technician') ⇔ tenant_id IS NULL

tenant_memberships (                          -- serwisant ↔ klient
  user_id uuid, tenant_id uuid, can_control boolean DEFAULT false, PK(user_id, tenant_id))

invitations (id uuid, tenant_id NULL, email, role, token_hash, expires_at, accepted_at NULL, created_by)
```

### Producenci i konta

```sql
provider_accounts (
  id uuid PK, tenant_id uuid NOT NULL, provider text,           -- 'viessmann'
  external_user_id text NULL, label text,
  refresh_token_enc bytea, access_token_enc bytea NULL, access_expires_at timestamptz NULL,
  scopes text, status text CHECK (status IN ('active','reauth_required','rate_limited','disabled')),
  status_reason text NULL, status_since timestamptz,
  budget_limit int DEFAULT 1450, budget_window_s int DEFAULT 86400, budget_reserve_pct int DEFAULT 15,
  short_limit int DEFAULT 120, short_window_s int DEFAULT 600,
  created_at, updated_at)

api_calls (                                    -- każde wywołanie API producenta (do budżetu i diagnostyki)
  id bigserial, provider_account_id uuid, ts timestamptz, kind text,   -- poll|command|discover|refresh_token
  device_id uuid NULL, http_status int NULL, duration_ms int, error_type text NULL)
  -- hypertable; retencja 35 dni; indeks (provider_account_id, ts DESC)

oauth_states (state text PK, code_verifier text, tenant_id, user_id, provider, expires_at)

discovered_devices (                           -- cache drzewa z discover
  provider_account_id uuid, installation_id text, gateway_serial text, device_id text,
  model text NULL, device_type text NULL, raw jsonb, seen_at, PK(provider_account_id, installation_id, gateway_serial, device_id))
```

### Urządzenia i cechy

```sql
devices (
  id uuid PK, tenant_id uuid NOT NULL, provider_account_id uuid, provider text,
  external_ids jsonb,                          -- {installationId, gatewaySerial, deviceId}
  model text, serial text NULL, display_name text, description text NULL,
  location_text text NULL, lat numeric NULL, lon numeric NULL,
  mode text CHECK (mode IN ('read','control')) DEFAULT 'read',
  poll_interval_s int NULL,                    -- NULL = automatyczny wg budżetu
  next_poll_at timestamptz, last_polled_at NULL, last_seen_at NULL,
  status text CHECK (status IN ('unknown','online','offline','error','rate_limited')) DEFAULT 'unknown',
  status_since timestamptz, status_detail text NULL,
  commands_per_hour_limit int DEFAULT 10,
  created_at, updated_at, archived_at NULL,
  UNIQUE (provider_account_id, (external_ids->>'installationId'), (external_ids->>'gatewaySerial'), (external_ids->>'deviceId')))

feature_definitions (
  id uuid PK, tenant_id uuid NOT NULL, device_id uuid,
  feature_name text,                           -- dokładnie jak w API
  is_enabled boolean, is_ready boolean,
  group_key text,                              -- wyliczone: circuits.0 | dhw | heat_source | sensors | ... | other
  properties_schema jsonb,                     -- {prop: {type, unit}}
  commands_schema jsonb,                       -- {cmd: {isExecutable, params:{...}}}  (bez uri)
  command_uris jsonb,                          -- {cmd: uri}  — używać przy wykonaniu
  unsupported_commands text[] DEFAULT '{}',    -- komendy, które zwróciły 404 mimo isExecutable
  first_seen_at, last_seen_at, UNIQUE (device_id, feature_name))

feature_latest (                               -- ostatnia wartość; z tego czytają widoki
  tenant_id uuid NOT NULL, device_id uuid, feature_name text, property_name text,
  value_num double precision NULL, value_bool boolean NULL, value_text text NULL, value_json jsonb NULL,
  unit text NULL, ts_device timestamptz NULL, ts_polled timestamptz,
  PK (device_id, feature_name, property_name))

feature_values (                               -- historia (hypertable po ts_polled)
  device_id uuid, feature_name text, property_name text,
  ts_polled timestamptz, ts_device timestamptz NULL,
  value_num double precision NULL, value_bool boolean NULL, value_text text NULL,
  tenant_id uuid NOT NULL)
  -- SELECT create_hypertable('feature_values','ts_polled', chunk_time_interval => interval '7 days');
  -- kompresja: segmentby (device_id, feature_name, property_name), orderby ts_polled DESC, po 7 dniach
  -- indeks: (device_id, feature_name, property_name, ts_polled DESC)
  -- retencja surowych: parametr RAW_RETENTION_DAYS (NULL = bez limitu)

feature_values_1h  -- continuous aggregate: time_bucket('1 hour'), min/avg/max/last(value_num), count
feature_values_1d  -- continuous aggregate: time_bucket('1 day'), min/avg/max/last, count
  -- odświeżanie: 1h co 15 min (okno 3 h), 1d co 1 h (okno 2 d)

device_status_history (device_id, tenant_id, status, since timestamptz, until NULL, detail)
```

**Zasada zapisu historii** (`ingest/services.py`): dla każdej property numerycznej/bool/string
zapisujemy wiersz, gdy wartość różni się od `feature_latest` **lub** minęło ≥ 1 h od ostatniego
zapisu (żeby wykresy nie miały dziur przy stałej wartości). JSON/Schedule — tylko `feature_latest`
+ zmiana zapisywana w `feature_json_history` (device_id, feature_name, property_name, ts, value_json)
przy zmianie hash-u.

### Sterowanie i audyt

```sql
commands (
  id uuid PK, tenant_id uuid NOT NULL, device_id uuid, user_id uuid, acted_as_operator boolean,
  feature_name text, command_name text, params jsonb,
  value_before jsonb NULL, value_after jsonb NULL,
  status text CHECK (status IN ('draft','confirmed','executing','succeeded','failed','verify_pending','verified','verify_mismatch','rejected','expired')),
  sensitive boolean, reauth_verified boolean,
  reject_reason text NULL, api_status int NULL, api_response jsonb NULL,
  ip inet, user_agent text, created_at, confirmed_at NULL, executed_at NULL, verified_at NULL)

audit_log (
  id bigserial, tenant_id uuid NULL, user_id uuid NULL, action text, target_type text, target_id uuid NULL,
  details jsonb, ip inet NULL, ts timestamptz)  -- append-only; brak UPDATE/DELETE dla roli aplikacji
```

### Alarmy, raporty, zadania, słownik

```sql
alerts (id uuid, tenant_id, device_id NULL, type text, severity text, message text,
        opened_at, closed_at NULL, acknowledged_by NULL, acknowledged_at NULL)
alert_rules (id uuid, tenant_id, device_id NULL, type text, config jsonb, enabled boolean)
  -- typy v1: device_offline{minutes}, value_out_of_range{feature,property,min,max}, device_message

report_schedules (id uuid, tenant_id, name, report_type, device_ids uuid[], features text[],
                  period text, resolution text, recipients text[], cron text, enabled, last_run_at)
report_files (id uuid, tenant_id, schedule_id NULL, requested_by, report_type, params jsonb,
              file_path, format text, created_at, expires_at)

jobs (id bigserial, kind text, payload jsonb, tenant_id uuid NULL, provider_account_id uuid NULL,
      run_at timestamptz, priority int DEFAULT 100, attempts int, max_attempts int, locked_at NULL,
      locked_by NULL, status text, last_error NULL, created_at)
  -- indeks (status, run_at, priority); pobieranie: FOR UPDATE SKIP LOCKED

feature_labels (feature_name_pattern text PK, label_pl text, description_pl text, group_key NULL, sort int)
  -- słownik globalny (operator); pattern z wildcard dla indeksów: heating.circuits.*.sensors.temperature.supply
```

## Reguły grupowania `group_key` (`devices/grouping.py`)

Kolejność dopasowania (pierwsze trafienie):

| Prefiks / wzorzec | group_key |
|---|---|
| `device.messages`, `*.errors` | `messages` |
| `device.` | `device` |
| `heating.circuits.{N}.` | `circuits.{N}` |
| `heating.dhw.` | `dhw` |
| `heating.burners.`, `heating.compressors.`, `heating.boiler.` (bez `sensors`) | `heat_source` |
| `heating.solar.` | `solar` |
| `ventilation.` | `ventilation` |
| `heating.buffer.` | `buffer` |
| `*.sensors.` | `sensors` |
| `heating.power.`, `heating.gas.`, `*.statistics`, `*.consumption` | `statistics` |
| pozostałe | `other` |

Wzorce poza `device.`, `heating.circuits.`, `heating.dhw.`, `heating.burners.`, `heating.boiler.`,
`heating.sensors`, `heating.solar` są [ZAŁOŻENIE]; tabela `feature_labels.group_key` nadpisuje regułę.

## Szyfrowanie tokenów

- Klucz główny `TOKEN_MASTER_KEY` (32 B, base64) w env, **nie** w DB, **nie** w tym samym backupie.
- Klucz per tenant: `HKDF(master, info=tenant_id)`. Algorytm: AES-256-GCM, nonce 12 B losowy,
  format `v1|nonce|ciphertext|tag`. Moduł `providers/crypto.py`, wersjonowany dla rotacji.

## Retencja i objętość

- `feature_values`: bez limitu (domyślnie); kompresja po 7 dniach. Parametr `RAW_RETENTION_DAYS`.
- `api_calls`: 35 dni. `jobs` zakończone: 14 dni. `report_files`: 180 dni. `audit_log`, `commands`: bez limitu.
- Szacunek przy 500 urządzeniach: ~10 mln wierszy historii/dobę → 20–40 GB/rok po kompresji
  (szacunek do weryfikacji na rzeczywistych zrzutach).
