# Runbook operatora (Wodmiar)

Procedury dla osoby utrzymującej Termolink na VPS. Polecenia wykonuje się w katalogu `deploy/`
na serwerze; skrót `C` = `docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## 1. Wdrożenie / aktualizacja

1. CI (GitHub Actions) po merge do `main` buduje obrazy i publikuje je w GHCR z tagami `latest`
   i `<git-sha>`.
2. Na VPS: ustaw `IMAGE_TAG=<git-sha>` w `.env` (albo zostaw `latest`), potem
   `C pull && C up -d`. Usługa `migrate` wykonuje `migrate` + `ensure_app_db_role`, a `backend`
   i `worker` startują dopiero po jej sukcesie. Usługa `frontend` kopiuje zbudowaną aplikację do
   wolumenu Caddy.
3. Sprawdź `https://<APP_DOMAIN>/api/v1/health` → `{"status":"ok","db":true,"worker":true}` i
   `C ps` (wszystko `running`/`healthy`, `migrate` i `frontend` `exited 0`).
4. **Rollback**: ustaw poprzedni `IMAGE_TAG`, `C up -d`. Migracje są projektowane jako
   „expand/contract”, więc kod z poprzedniego taga działa na nowszym schemacie. Jeśli migracja była
   nieodwracalna i trzeba cofnąć dane — §5.

## 2. Ponowna autoryzacja konta Viessmann klienta (`reauth_required`)

Objaw: alarm „Konto producenta … wymaga ponownego logowania”, urządzenia klienta przestają się
odświeżać, karta konta w `/admin/tenants/<id>` pokazuje status `reauth_required`.

1. Zaloguj się jako operator, otwórz klienta → karta „Konto Viessmann” → **Połącz ponownie**.
2. Zaloguj się w portalu Viessmann **danymi klienta** (klient robi to sam lub udostępnia sesję —
   operator nie przechowuje haseł klientów).
3. Po powrocie status zmienia się na `active`, worker wznawia odczyty w kolejnym tiku (≤ 5 s).
4. Jeśli błąd powtarza się co kilka dni: sprawdź, czy Client ID nie został zmieniony w portalu
   Viessmann i czy `OAUTH_REDIRECT_BASE` w `.env` odpowiada zarejestrowanemu redirect URI.

## 3. Dodanie serwisanta i nadanie mu dostępu do klienta

1. `/admin/technicians` → „Zaproś” → e-mail serwisanta (zaproszenie ważne 72 h; serwisant musi
   włączyć 2FA przy pierwszym logowaniu — bez tego API odpowiada 403 `totp_setup_required`).
2. `/admin/technicians/<id>` → „Dodaj klienta” → wybierz klienta i zaznacz `can_control` tylko,
   jeśli serwisant ma sterować (domyślnie wyłącznie odczyt).
3. Odebranie dostępu: usuń członkostwo; sesje serwisanta pozostają, ale każde żądanie do tego
   klienta kończy się 404.

## 4. Rotacja klucza szyfrowania tokenów (`TOKEN_MASTER_KEY`)

Tokeny OAuth klientów są zaszyfrowane AES-256-GCM kluczem pochodnym z `TOKEN_MASTER_KEY`
(`docs/08`). Rotacja:

1. Wygeneruj nowy klucz: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
2. Ustaw w `.env`: `TOKEN_MASTER_KEY=<nowy>` i `TOKEN_MASTER_KEY_PREVIOUS=<stary>`.
3. `C up -d backend worker` — aplikacja odczytuje tokeny starym kluczem i przy najbliższym
   odświeżeniu tokenu zapisuje je nowym (kolumna `token_key_version`).
4. Po tygodniu sprawdź `C exec backend python manage.py shell -c "from apps.providers.models import ProviderAccount as P; print(P.objects.exclude(token_key_version=2).count())"`
   — gdy 0, usuń `TOKEN_MASTER_KEY_PREVIOUS`. Konta, których nie udało się przepisać, wymagają
   ponownej autoryzacji (§2).

   > Uwaga: mechanizm `TOKEN_MASTER_KEY_PREVIOUS` jest zaplanowany w `docs/08`; do czasu jego
   > wdrożenia rotacja oznacza ponowną autoryzację wszystkich kont (§2) — zaplanuj ją z klientami.

## 5. Backup i przywracanie

- Backup robi usługa `backup` codziennie o 02:00 (`BACKUP_SCHEDULE`): `pg_dump -Fc` → szyfrowanie
  `age` kluczem publicznym `BACKUP_AGE_RECIPIENT` → `/backups` (retencja 30 dni) → opcjonalnie
  `rclone` do `RCLONE_REMOTE`. Wynik ostatniego backupu: `/backups/LAST_STATUS` (`ok …` albo
  `failed …`); worker podnosi alarm operatora `backup_failed`, gdy plik zgłasza błąd lub jest
  starszy niż 26 h.
- **Klucz prywatny `age` (AGE-SECRET-KEY-1…) trzymaj poza serwerem** (menedżer haseł Wodmiar).
  Bez niego backupy są bezużyteczne.
- Ręczny backup: `C exec backup backup.sh`.
- **Przywracanie** (testowane co kwartał na staging, wpis w `ops/restore-log.md`):
  1. `C stop backend worker caddy`
  2. `C run --rm -e AGE_SECRET_KEY="AGE-SECRET-KEY-1…" backup restore.sh /backups/termolink-<data>.dump.age`
     (plik z rclone: najpierw `C run --rm backup rclone copy "$RCLONE_REMOTE/<plik>" /backups/`)
  3. `C up -d` — usługa `migrate` odtwarza rolę aplikacji i granty (`ensure_app_db_role`).
  4. Sprawdź logowanie, listę urządzeń i ostatnie odczyty; worker sam dogoni harmonogram odczytów.

## 6. Monitoring i alarmy operatora

- Zewnętrzny uptime-check: `GET https://<APP_DOMAIN>/api/v1/health` co 1–5 min; `503` gdy baza
  nie odpowiada **lub** żaden worker nie zgłosił się od 2 min (`"worker": false`).
- Alarmy do `ALERT_EMAIL_OPERATOR`: `worker_down`, `provider_account` (reauth/limit),
  `verify_mismatch`, `backup_failed`. Lista: `/admin/alerts` (API) — w UI jako panel operatora.
- Dysk: `df -h /var/lib/docker` — przy < 15 % wolnego zmniejsz `RAW_RETENTION_DAYS` (domyślnie bez
  limitu; agregaty 1h/1d zostają) albo powiększ dysk. Rozmiar bazy:
  `C exec db psql -U termolink -c "select pg_size_pretty(pg_database_size('termolink'))"`.
- Budżet API Viessmann: karta konta w `/admin/tenants/<id>` (użycie/limit/reset). Przy
  `rate_limited` worker sam wstrzymuje odczyty do `status_until`.

## 7. Blokada / odblokowanie klienta

- `/admin/tenants/<id>` → „Sterowanie” (globalna blokada komend) albo „Dezaktywuj” (użytkownicy
  klienta nie mogą się zalogować; dane i odczyty pozostają).
- Awaryjne wylogowanie wszystkich: `C exec backend python manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.

## 8. Logi

`C logs -f --tail 200 backend worker caddy`. Logi Caddy są w JSON (adres, ścieżka, status, czas).
Audyt działań użytkowników: tabela `audit_log` (append-only) — `/admin/audit` w UI operatora
(etap „po v1”), do tego czasu `C exec db psql -U termolink -c "select ts,action,user_id,details from audit_log order by ts desc limit 50"`.
