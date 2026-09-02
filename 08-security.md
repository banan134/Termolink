# 08 — Bezpieczeństwo

> Nie istnieje system „w 100 % niemożliwy do złamania”. Cel: atak trudny i drogi, pojedyncza luka
> nie daje dostępu do wszystkiego, włamanie szybko wykrywalne, dane odtwarzalne.
> **Przed produkcją: niezależny test penetracyjny** (pozycja w budżecie projektu).

## Uwierzytelnianie

- Hasła: Argon2id (`django[argon2]`), min. 12 znaków, walidatory Django + lista popularnych haseł.
- Blokada: po 10 nieudanych próbach na konto lub IP → opóźnienie narastające (1, 2, 4… min, max 30);
  `django-axes` lub własna tabela `login_attempts`.
- 2FA TOTP (`pyotp`): **obowiązkowe** dla `superadmin` i `technician` (bez 2FA nie ma logowania);
  **wymagane** dla `tenant_admin` do sterowania; opcjonalne dla `tenant_user`. 10 kodów zapasowych (hash).
- Brak samodzielnej rejestracji; zaproszenia z tokenem (hash w DB), ważność 72 h, jednorazowe.
- Reset hasła: token 30 min, jednorazowy, unieważnia sesje.
- `reauth` (hasło + TOTP) dla operacji wrażliwych: komendy wrażliwe, zmiana trybu urządzenia,
  zmiana e-maila, wyłączenie 2FA, odłączenie konta producenta. Ważność 5 min, w sesji.

## Sesje

- `django.contrib.sessions`, backend DB, cookie `HttpOnly; Secure; SameSite=Lax`, nazwa niestandardowa.
- Wygaśnięcie: 12 h bezczynności, max 7 dni. Rotacja ID po logowaniu. Lista sesji w profilu, wylogowanie
  zdalne. Zmiana hasła → unieważnienie pozostałych sesji.
- CSRF: `X-CSRFToken` (Django CSRF) — frontend pobiera z cookie `csrftoken`.

## Autoryzacja i izolacja

- RBAC w `permissions.py` + egzekwowanie w `services` (podwójnie).
- RLS w PostgreSQL (`03-data-model.md`) — trzecia, niezależna warstwa.
- 404 zamiast 403 dla zasobów spoza tenanta.
- UUID v4 dla wszystkich identyfikatorów w URL.
- Test automatyczny izolacji dla każdego endpointu (`12-testing.md`).

## Sekrety i tokeny producenta

- `TOKEN_MASTER_KEY` w env (plik `.env` z uprawnieniami 600 na VPS, poza repozytorium, poza backupem DB).
- Tokeny szyfrowane AES-256-GCM kluczem pochodnym per tenant (`03-data-model.md`). Nigdy w logach,
  nigdy w odpowiedziach API, nigdy we frontendzie.
- Rotacja klucza: `manage.py rotate_token_key --old --new` (re-encrypt); format wersjonowany `v1|…`.
- Awaryjne unieważnienie: `manage.py revoke_provider_tokens --all|--tenant` → wszystkie konta
  `reauth_required`; operator ponawia autoryzację u klientów.

## Aplikacja WWW

- Nagłówki (Caddy + `django-csp`): HSTS `max-age=31536000; includeSubDomains; preload`,
  `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'(tylko jeśli konieczne dla wykresów — dążyć do usunięcia); img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- Walidacja wejścia: DRF serializers + `pydantic` dla payloadów adapterów. Brak surowego SQL z konkatenacją.
- Rate limiting (Caddy + DRF throttling): login 5/min/IP, reset 3/h/IP, `/commands` 30/h/user, API 600/min/user.
- Upload logo: tylko PNG/SVG, ≤ 1 MB, SVG sanitizowany (usunięcie skryptów) lub konwertowany do PNG.
- Zależności: Dependabot/Renovate; `pip-audit`, `npm audit` w CI; obrazy z pinowanymi digestami.
- Logi strukturalne (JSON) bez sekretów, bez treści haseł/tokenów; `request_id` w każdym wpisie.

## Serwer (VPS)

- Ubuntu 24.04 LTS, `unattended-upgrades` (security), użytkownik `termolink` bez sudo dla usług.
- Firewall: tylko 80/443 publicznie; SSH tylko kluczem, `PasswordAuthentication no`, fail2ban;
  zalecane SSH przez WireGuard.
- Kontenery: `db`, `worker` bez publikowanych portów; sieć wewnętrzna Compose; `read_only: true`
  gdzie możliwe; `no-new-privileges`.
- Backup: `pg_dump` co noc + Timescale-safe (`--format=custom`), szyfrowany (age/gpg), wysyłany
  poza VPS (S3/inny dostawca); retencja 30 dziennych + 12 miesięcznych; **test odtworzenia co kwartał**.
  Klucz `TOKEN_MASTER_KEY` przechowywany osobno (menedżer haseł operatora).
- Monitoring/alerty operatora: worker heartbeat, błędy API/h, masowe nieudane logowania, zmiana trybu
  urządzenia, komendy poza 6:00–22:00, miejsce na dysku < 15 %, nieudany backup.

## Ochrona urządzeń

- Domyślnie `read`. `control` tylko przez operatora z reauth.
- Allowlist: wyłącznie komendy z ostatniego odczytu z `executable=true`.
- Walidacja constraints po stronie portalu (drugi bezpiecznik po Viessmann).
- Limit komend/h per urządzenie, potwierdzenie 2-etapowe, reauth dla wrażliwych, weryfikacja po wykonaniu,
  pełny audit (`07-control-flow.md`).

## Prywatność (RODO)

- Dane osobowe: e-mail, imię/nazwisko (opcjonalnie), adres montażu, IP w logach. Rejestr w `docs/`
  operatora. Retencja IP w `audit_log`: bezterminowo (uzasadnienie: bezpieczeństwo) — do decyzji operatora.
- Usunięcie klienta: archiwizacja + po 30 dniach anonimizacja użytkowników i usunięcie tokenów;
  historia pomiarów pozostaje jako dane urządzenia (bez PII) — do potwierdzenia z operatorem.
