# 04 — REST API portalu (kontrakt)

Base: `/api/v1`. JSON. Uwierzytelnianie: sesja (cookie `HttpOnly; Secure; SameSite=Lax`) + nagłówek
`X-CSRFToken` dla metod modyfikujących. Schemat OpenAPI generowany przez `drf-spectacular` pod
`/api/schema/`; frontend generuje z niego typy TS (`openapi-typescript`).

Konwencje:
- Zasób spoza tenanta użytkownika → **404** (nie 403), żeby nie ujawniać istnienia.
- Błędy: `{ "error": { "code": "…", "message": "…", "fields": {…} } }`.
- Listy: `?page=&page_size=` (max 200), odpowiedź `{ "results": [...], "count": n }`.
- Czas: ISO 8601 UTC. UI konwertuje na strefę tenanta.
- Wszystkie odpowiedzi widoków czytane z DB; brak wywołań API producenta w cyklu żądania.

## Auth

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/auth/csrf` | 204; ustawia cookie `csrftoken` (SPA przed pierwszą mutacją) |
| POST | `/auth/login` | `{email, password, totp?}` → 200 `{user: …jak /auth/me}` + sesja; 401 `invalid_credentials`; 428 `totp_required`; 429 `login_locked` (`retry_after_s`); throttling 5/min/IP |
| POST | `/auth/logout` | |
| GET | `/auth/me` | `{id, email, role, tenant: {id,name} \| null, totp_enabled, allowed_tenants[], ui_theme}` |
| PATCH | `/auth/me` | `{ui_theme: 'light'\|'dark'}` |
| POST | `/auth/password/change` | wymaga starego hasła; unieważnia inne sesje |
| POST | `/auth/password/reset-request` `{email}` → zawsze 204 (e-mail z linkiem `PUBLIC_BASE_URL/reset?token=…`, throttling 3/h/IP) / `/auth/password/reset` `{token, password}` → 204; 400 `invalid_token` | tokeny jednorazowe, 30 min; reset unieważnia wszystkie sesje |
| POST | `/auth/totp/setup` → `{secret, otpauth_url}` (sekret tymczasowo w sesji); POST `/auth/totp/enable {code}` → `{backup_codes[]}` (raz); POST `/auth/totp/disable {password, code}` (kod TOTP lub zapasowy) | |
| POST | `/auth/reauth` | `{password, totp?}` → 204; 428 `totp_required` gdy 2FA włączone; ustawia `reauth_until` (5 min) w sesji; używane przez sterowanie i zmiany wrażliwe |
| GET | `/auth/sessions` / DELETE `/auth/sessions/{id}` | aktywne sesje: `[{id, ip, user_agent, created_at, last_seen_at, current}]`; usunięcie bieżącej = wylogowanie |
| POST | `/auth/invitations/accept` | `{token, password}` → 200 `{user}` + sesja (użytkownik utworzony z roli/tenanta zaproszenia); 400 `invalid_token`; e-mail zaproszenia z linkiem `PUBLIC_BASE_URL/invite/<token>` |

## Operator: klienci (superadmin, technician w zakresie przypisań)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET/POST | `/admin/tenants` | lista z `devices_count, online_count, budget:{used,limit,reset_at}` |
| GET/PATCH/DELETE | `/admin/tenants/{id}` | `control_allowed`, `report_header_text`, `timezone`; DELETE (tylko superadmin) usuwa klienta trwale z użytkownikami, urządzeniami, historią, alarmami i raportami (wpis `tenant.deleted` w audycie) |
| POST/DELETE | `/admin/tenants/{id}/logo` | multipart, PNG/SVG ≤ 1 MB |
| GET | `/admin/tenants/{id}/users` | `{results:[{id,email,role,totp_enabled,is_active,last_login}], count, invitations:[…oczekujące]}` |
| POST | `/admin/tenants/{id}/invitations` | `{email, role: tenant_admin\|tenant_user}` → 201; 409 `email_taken` |
| GET | `/admin/technicians` | lista serwisantów (superadmin) |
| GET/POST | `/tenants/{tid}/users`, POST `/tenants/{tid}/invitations` | to samo dla `tenant_admin` własnego klienta (docs/14 B7) i operatora |
| GET/POST/DELETE | `/admin/technicians/{user_id}/memberships` | `{tenant_id, can_control}` |
| GET/PUT | `/admin/feature-labels` | słownik etykiet (bulk) |
| GET | `/admin/audit` | filtry: tenant, user, action, zakres dat |
| GET | `/admin/system/health` | worker heartbeat, zaległe joby, błędy API/h |

## Konta producentów

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/tenants/{tid}/provider-accounts` | status, budżet, ostatnie błędy |
| POST | `/tenants/{tid}/provider-accounts/viessmann/authorize` | → `{redirect_url}` (operator) |
| GET | `/oauth/viessmann/callback?code&state` | poza `/api`; kończy redirectem do UI |
| POST | `/tenants/{tid}/provider-accounts/{id}/discover` | kolejkuje discover → `{job_id}` |
| GET | `/tenants/{tid}/provider-accounts/{id}/discovered` | drzewo instalacja→bramka→urządzenie z flagą `already_added` |
| PATCH | `/tenants/{tid}/provider-accounts/{id}` | `label, budget_limit, budget_reserve_pct, status:'disabled'` (operator) |
| DELETE | `/tenants/{tid}/provider-accounts/{id}` | odłącza; urządzenia → `archived` |

## Urządzenia

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/tenants/{tid}/devices` | karty: `{id, display_name, model, location_text, description, mode, status, status_since, last_seen_at, highlights:[{feature,property,label,value,unit}]}` |
| POST | `/tenants/{tid}/devices` | operator: `{provider_account_id, external_ids, display_name, description, location_text, lat, lon, mode, poll_interval_s}` → tworzy + job poll |
| GET | `/tenants/{tid}/devices/{id}` | szczegóły + `budget` konta + `capabilities:{can_control:boolean, reasons:[]}` dla bieżącego użytkownika |
| PATCH | `/tenants/{tid}/devices/{id}` | tenant_admin: `display_name, description, location_text, lat, lon`; operator dodatkowo `mode, poll_interval_s, commands_per_hour_limit` (zmiana `mode` wymaga `reauth`) |
| DELETE | `/tenants/{tid}/devices/{id}` | archiwizacja (historia zostaje); `?permanent=1` (operator) usuwa trwale razem z historią pomiarów |
| POST | `/tenants/{tid}/devices/{id}/refresh` | „Odśwież teraz” → `{job_id}`; 429 jeśli budżet < rezerwa |
| GET | `/tenants/{tid}/devices/{id}/insights?period=week\|month` | „Co się zmieniło”: liczniki (przyrost), czujniki (średnia) i dostępność — bieżące 7/30 dni vs poprzednie, z `delta`/`delta_pct` |
| GET | `/admin/overview` | operator: klienci → urządzenia (karta + `lat/lon` + `open_alerts`), `totals` (statusy, alarmy, tryb sterowania), konta producentów z budżetem |
| GET | `/tenants/{tid}/devices/{id}/insights?period=week\|month` | „Co się zmieniło”: liczniki (przyrost), czujniki (średnia) i dostępność — bieżące 7/30 dni vs poprzednie, z `delta`/`delta_pct` |
| GET | `/admin/overview` | operator: klienci → urządzenia (karta + `lat/lon` + `open_alerts`), `totals` (statusy, alarmy, tryb sterowania), konta producentów z budżetem |
| GET | `/tenants/{tid}/devices/{id}/features` | `[{feature_name, label_pl, group_key, is_enabled, properties:{name:{type,unit,value,ts_device}}, commands:{name:{executable, params}}, unsupported_commands}]` z `feature_latest` |
| GET | `/tenants/{tid}/devices/{id}/history` | `?feature=&property=&from=&to=&resolution=raw\|1h\|1d&max_points=2000` → `{unit, resolution, points:[{ts, value}] \| [{ts,min,avg,max,last,count}], gaps:[{from,to}], stats:{min:{ts,value},max:{ts,value},avg,last,count,availability_pct,delta?}, markers:[{ts,type:'command',label}]}`; auto-resolution gdy brak parametru (≤ 48 h raw, ≤ 90 d 1h, > 90 d 1d); surowe > max_points → downsampling LTTB |
| POST | `/tenants/{tid}/history/multi` | `{series:[{device_id,feature,property}], from, to, resolution?}` → tablica jak wyżej (do 6 serii; porównania w eksploratorze) |
| GET | `/tenants/{tid}/devices/{id}/history.csv` | te same parametry, eksport CSV bieżącego widoku |
| GET | `/tenants/{tid}/devices/{id}/status-history` | |
| GET | `/tenants/{tid}/devices/{id}/messages` | cechy grupy `messages` + historia JSON |

`highlights` na kartach: wybierane z `feature_labels.highlight=true` per typ urządzenia, w kolejności
`sort`; fallback: temperatura zewnętrzna, zasilanie obiegu 0, CWU (jeśli istnieją).

## Sterowanie (`07-control-flow.md`)

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/tenants/{tid}/devices/{id}/commands` | `{feature_name, command_name, params}` → tworzy `draft`: `{id, status, value_before, value_after, sensitive, expires_at, …}`; 403 `control_not_allowed` z `reasons: []`; 422 `constraint_violation` (`fields`) lub `command_not_available` |
| POST | `/tenants/{tid}/commands/{cid}/confirm` | `{acknowledged: true}`; jeśli `sensitive` → wymaga `reauth_until > now` (428 `reauth_required`) → `confirmed` + job |
| GET | `/tenants/{tid}/commands/{cid}` | status + `job:{kind,status,error}`; UI polluje do `verified`/`failed`/`verify_mismatch`/`expired` |
| GET | `/tenants/{tid}/commands` | dziennik zmian: `{results:[…, device_name], count}`; filtry `device`, `status`, `page`, `page_size` (≤ 200) |

## Ustawienia systemu (superadmin)

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET/PUT | `/admin/settings/mail` | SMTP operatora: `enabled, host, port, username, password (tylko zapis; API zwraca `has_password`), use_tls/use_ssl, from_email, timeout_s` + wynik ostatniego testu. Hasło szyfrowane AES-GCM (scope `mail`). Gdy `enabled`, backend poczty (`apps.core.mail.DatabaseEmailBackend`) używa tych ustawień, inaczej `SMTP_URL` z env, a bez niego logów konsoli. |
| POST | `/admin/settings/mail/test` | `{to}` → wysyła wiadomość testową z zapisanych ustawień; `{ok, error}` zapisane na wierszu |

## Alarmy

GET/PATCH `/tenants/{tid}/alerts` (`acknowledged`), GET/POST/PATCH/DELETE `/tenants/{tid}/alert-rules`.

## Raporty (`10-reports.md`)

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/tenants/{tid}/reports/preview` | `{report_type, device_ids, from, to, resolution, features?}` → dane do wykresów/tabel (synchronicznie, z agregatów, limit 50 tys. punktów) |
| POST | `/tenants/{tid}/reports/jobs` | `{...jak wyżej, format:'pdf'\|'csv'}` → `{job_id}` |
| GET | `/tenants/{tid}/reports/files` , GET `/tenants/{tid}/reports/files/{id}/download` | |
| GET/POST/PATCH/DELETE | `/tenants/{tid}/report-schedules` | |

## Zadania

GET `/jobs/{id}` → `{status: queued|running|done|failed, result?, error?}` (tylko własne/tenanta).

## Uprawnienia — macierz

| Endpoint (grupa) | superadmin | technician (przypisany) | tenant_admin | tenant_user |
|---|---|---|---|---|
| `/admin/*` | ✔ | tylko tenants z membership (bez feature-labels, system) | ✖ | ✖ |
| provider-accounts | ✔ | ✔ | GET | ✖ |
| devices GET | ✔ | ✔ | ✔ | ✔ |
| devices POST/DELETE, PATCH `mode` | ✔ | ✔ | ✖ | ✖ |
| devices PATCH nazwa/opis/lokalizacja | ✔ | ✔ | ✔ | ✖ |
| refresh | ✔ | ✔ | ✔ | ✖ |
| commands | ✔ | jeśli `can_control` | jeśli `device.mode='control'` ∧ `tenant.control_allowed` ∧ `totp_enabled` | **✖ zawsze** |
| reports, alerts GET | ✔ | ✔ | ✔ | ✔ |
| alert-rules, report-schedules zapis | ✔ | ✔ | ✔ | ✖ |

Uprawnienia implementowane jako klasy `permissions.py` per app **oraz** egzekwowane w `services`
(podwójnie — widok i serwis), żeby wywołania z workera/CLI też podlegały regułom.
