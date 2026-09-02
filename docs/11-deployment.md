# 11 — Wdrożenie

## Środowiska

| | dev (lokalnie) | staging (VPS) | prod (VPS) |
|---|---|---|---|
| Domena | `localhost` | `staging.termolink.<domena>` | `app.termolink.<domena>` (TODO: docelowa domena) |
| Viessmann Client ID | ten sam Client ID, redirect URI dev wpisany w portalu Viessmann | osobny Client ID zalecany | osobny Client ID |
| Dane | fixtures + 1 urządzenie testowe | urządzenia testowe operatora | klienci |

## Pliki Compose

Jeden `docker-compose.yml` (baza) + nakładki: `docker-compose.dev.yml` (komputer programisty, `docs/15-local-development.md`) i `docker-compose.prod.yml` (VPS). Produkcja: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

## `deploy/docker-compose.yml` (szkic — baza)

```yaml
services:
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes: [./Caddyfile:/etc/caddy/Caddyfile:ro, caddy_data:/data, frontend_dist:/srv/frontend:ro]
    depends_on: [backend]
  backend:
    build: ../backend
    command: gunicorn termolink.wsgi --workers 4 --bind 0.0.0.0:8000 --timeout 30
    env_file: .env
    depends_on: [db]
    volumes: [media:/app/media]
    read_only: true
    tmpfs: [/tmp]
    security_opt: [no-new-privileges:true]
  worker:
    build: ../backend
    command: python manage.py run_worker --concurrency 20
    env_file: .env
    depends_on: [db]
    volumes: [media:/app/media]
    deploy: { replicas: 1 }          # zwiększyć przy >200 urządzeniach
  db:
    image: timescale/timescaledb:latest-pg16
    env_file: .env
    volumes: [pgdata:/var/lib/postgresql/data]
    # brak ports: — dostęp tylko z sieci compose
  backup:                                          # dodawany w etapie 6 (wymaga konfiguracji age/rclone)
    image: prodrigestivill/postgres-backup-local   # lub własny skrypt pg_dump + age + rclone
    env_file: .env
    volumes: [backups:/backups]
volumes: { pgdata: {}, media: {}, caddy_data: {}, backups: {}, frontend_dist: {} }
```

Frontend budowany w CI (`vite build`) → katalog `frontend_dist` serwowany przez Caddy; `/api/*`,
`/oauth/*`, `/admin-django/*` (panel Django, tylko dla superadmina, za dodatkowym basic-auth w Caddy)
oraz `/static/*` (pliki statyczne Django dla panelu i Swaggera, serwowane przez WhiteNoise)
proxowane do `backend:8000`.

## `deploy/Caddyfile` (szkic)

```
app.termolink.example {
  encode zstd gzip
  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    X-Content-Type-Options nosniff
    Referrer-Policy strict-origin-when-cross-origin
    X-Frame-Options DENY
    Permissions-Policy "camera=(), microphone=(), geolocation=()"
  }
  @api path /api/* /oauth/* /admin-django/* /static/*
  handle @api { reverse_proxy backend:8000 }
  handle { root * /srv/frontend; try_files {path} /index.html; file_server }
  # rate limiting: plugin caddy-ratelimit lub egzekwowanie w DRF
}
```

## `.env.example`

```
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=app.termolink.example
DATABASE_URL=postgres://termolink:***@db:5432/termolink
TOKEN_MASTER_KEY=            # 32 B base64; generować: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
VIESSMANN_CLIENT_ID=
VIESSMANN_API_BASE=https://api.viessmann-climatesolutions.com/iot/v1
VIESSMANN_IAM_BASE=https://iam.viessmann-climatesolutions.com/idp/v3
OAUTH_REDIRECT_BASE=https://app.termolink.example
RAW_RETENTION_DAYS=          # puste = bez limitu
SMTP_URL=
ALERT_EMAIL_OPERATOR=
SENSITIVE_COMMANDS=setMode,setSchedule,setCurve,deactivate
```

## Procedury

- **Deploy**: CI buduje obrazy z tagiem = git SHA → na VPS `docker compose pull && docker compose up -d`
  → `manage.py migrate` uruchamiane jako job przed startem `backend` (`depends_on` + skrypt). Rollback:
  poprzedni tag + (jeśli migracja nieodwracalna) przywrócenie backupu — migracje projektować jako
  „expand/contract”, żeby rollback kodu nie wymagał rollbacku DB.
- **Backup**: co noc 02:00, `pg_dump -Fc`, szyfrowanie `age`, `rclone` do zewnętrznego magazynu;
  retencja 30 d + 12 m; test odtworzenia co kwartał na staging (udokumentowany w `ops/restore-log.md`).
- **Monitoring**: `/admin/system/health` + zewnętrzny uptime-check HTTPS; e-mail do operatora
  przy: brak heartbeatu workera, backup nieudany, dysk < 15 %, > 50 błędów API/h.
- **Aktualizacje**: `unattended-upgrades` OS; obrazy aplikacji aktualizowane przez CI co najmniej
  raz w miesiącu (bezpieczeństwo zależności).

## Wymagania VPS (start → docelowo)

- Start (6 urządzeń): 2 vCPU, 4 GB RAM, 40 GB SSD.
- Docelowo (500 urządzeń): 4–8 vCPU, 16 GB RAM, 200+ GB SSD (lub baza na osobnym hoście), zależnie
  od rzeczywistej objętości po roku (monitorować `pg_database_size`).
