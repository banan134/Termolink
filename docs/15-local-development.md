# 15 — Środowisko lokalne (Docker na komputerze)

Cel: cały Termolink (baza, backend, worker, frontend, proxy) uruchamia się na komputerze programisty
**jednym poleceniem**, bez instalowania Pythona, Node ani PostgreSQL na hoście. Claude Code pracuje
na lokalnym katalogu repozytorium; kod jest montowany do kontenerów, więc zmiany są widoczne od razu
(hot reload). Ten sam `docker-compose.yml` co na VPS + nakładka `docker-compose.dev.yml`.

## Wymagania na komputerze

- Docker Desktop (Windows/macOS) lub Docker Engine + Compose v2 (Linux). Na Windows: WSL 2 włączone.
- Git. Opcjonalnie `make` (na Windows: przez WSL lub użyj poleceń `docker compose` z tabeli niżej).
- Claude Code: aplikacja desktop (zakładka Code, środowisko **Local**) lub CLI w terminalu.
- Nic więcej — Python, Node, Postgres są wyłącznie w kontenerach.

## Struktura plików uruchomieniowych

```
deploy/
  docker-compose.yml        # baza wspólna (VPS i lokalnie)
  docker-compose.dev.yml    # nakładka dev: montowanie kodu, hot reload, porty, bez TLS
  docker-compose.prod.yml   # nakładka prod: Caddy z TLS, read-only, replicas
  Caddyfile                 # prod
  Caddyfile.dev             # dev: http://localhost:8080, proxy /api,/oauth,/admin-django,/static → backend, reszta → vite
  .env.example
backend/Dockerfile          # multi-stage: target dev (z narzędziami) i prod
frontend/Dockerfile         # dev: vite dev server; prod: build → statyczne pliki
Makefile
```

## Pierwsze uruchomienie

```bash
git clone <repo> termolink && cd termolink
make dev                                 # = docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
# `make dev` tworzy deploy/.env z .env.example, jeśli go nie ma; VIESSMANN_CLIENT_ID uzupełnić przed etapem 2.
# Bez `make` (Windows bez WSL): cp deploy/.env.example deploy/.env i powyższe polecenie docker compose.
```

Po starcie:

| Adres | Co |
|---|---|
| http://localhost:8080 | aplikacja (Caddy dev → frontend + /api) |
| http://localhost:8080/api/schema/swagger/ | OpenAPI |
| http://localhost:8080/admin-django/ | panel Django (tylko dev) |
| localhost:5432 | PostgreSQL (`termolink` / hasło z `.env`) — port wystawiony **tylko w dev** |
| http://localhost:8025 | Mailpit — podgląd wysłanych e-maili (dev) |

Pierwsze dane: `make seed` → operator `admin@termolink.local` / hasło z `.env` (`DEV_ADMIN_PASSWORD`),
2 klientów demo, urządzenia z fixtures, 30 dni syntetycznej historii. Skrypt odmawia działania,
jeśli `DJANGO_ENV != dev`.

## Polecenia (Makefile)

| `make …` | Równoważne `docker compose …` | Opis |
|---|---|---|
| `dev` | `-f … -f …dev.yml up --build` | start wszystkiego z logami |
| `up` / `down` | `up -d` / `down` | w tle / zatrzymanie (dane w wolumenie zostają) |
| `reset` | `down -v` | zatrzymanie + **usunięcie bazy** |
| `migrate` | `exec backend python manage.py migrate` | |
| `makemigrations` | `exec backend python manage.py makemigrations` | |
| `seed` | `exec backend python manage.py seed_demo` | dane demo |
| `test` | `exec backend pytest` + `exec frontend npm test` | |
| `lint` | ruff, mypy, eslint, tsc | |
| `shell` | `exec backend python manage.py shell` | |
| `psql` | `exec db psql -U termolink` | |
| `logs s=worker` | `logs -f worker` | logi jednej usługi |
| `worker` | `exec backend python manage.py run_worker --once` | jeden cykl workera ręcznie (debug) |

## Nakładka dev — co zmienia

- `backend`: `migrate` przy starcie, potem `runserver 0.0.0.0:8000` z autoreload, `DEBUG=1`, kod zamontowany `../backend:/app`,
  `DJANGO_ENV=dev`, target `dev` w Dockerfile (pytest, ruff, mypy, ipython w obrazie).
- `worker`: ten sam obraz, `run_worker --concurrency 4 --tick 5`; można zatrzymać (`docker compose stop worker`),
  gdy pracujemy tylko nad UI i nie chcemy zużywać budżetu API Viessmann.
- `frontend`: `vite --host` z HMR, `../frontend:/app`, `node_modules` w osobnym wolumenie (szybciej na Windows/macOS).
- `caddy`: `Caddyfile.dev`, port 8080, bez TLS.
- `db`: port 5432 wystawiony; `mailpit` dodany; `backup` wyłączony.
- Wolumen `pgdata_dev` osobny od produkcyjnego.

## Viessmann lokalnie

- W portalu deweloperskim Viessmann dodać redirect URI `http://localhost:8080/oauth/viessmann/callback`
  (obok produkcyjnego). To ten sam Client ID.
- Przebieg OAuth działa z localhost — przeglądarka wraca na localhost po logowaniu u Viessmanna.
- **Budżet API jest wspólny dla konta Viessmann** — lokalny worker i produkcja odpytujące to samo konto
  dzielą 1450/24 h. Dlatego w dev: `DEV_POLL_INTERVAL_S=600` domyślnie i worker zatrzymywany, gdy niepotrzebny.
- Do pracy bez sieci/bez zużywania budżetu: `VIESSMANN_MOCK=1` → adapter czyta odpowiedzi z
  `backend/tests/fixtures/viessmann/` zamiast z API (wartości lekko losowane, żeby wykresy żyły).

## Praca z Claude Code lokalnie

- Aplikacja desktop → zakładka Code → środowisko **Local** → folder repozytorium. Claude widzi
  `CLAUDE.md`, `docs/`, może uruchamiać `make test`, `make lint`, `docker compose …`.
- Docker musi działać na hoście; Claude uruchamia polecenia przez `docker compose exec`, nie potrzebuje
  Pythona na hoście.
- Podgląd aplikacji: `.claude/launch.json` z wpisem `url: http://localhost:8080` (bez własnego
  polecenia — Compose już działa), żeby panel Browser w Claude Code pokazywał Termolink.
- Sesje lokalne nie synchronizują się z telefonem; jeśli potrzebna mobilność — „Continue in → Claude
  Code on the Web” (wymaga repo na GitHubie i czystego drzewa roboczego).
- Zalecany rytm: tryb Plan → zatwierdzenie → Accept edits; jedno zadanie z `13-roadmap.md` = jedna gałąź = jeden PR.

## Repozytorium

- GitHub (prywatne) jako źródło prawdy i kopia zapasowa kodu — nawet przy pracy lokalnej.
- Gałęzie: `main` (stabilna, wdrażana na VPS), `feat/<etap>-<nazwa>` per zadanie. CI (lint + testy) na każdym PR.
- `.gitignore`: `deploy/.env`, `pgdata*`, `media/`, `node_modules/`, `__pycache__/`, `.claude/worktrees/`.
- Fixtures z rzeczywistych odpowiedzi API **po anonimizacji** (numery seryjne, ID instalacji) mogą być w repo.

## Typowe problemy

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| Wolny HMR/ruff na Windows | kod w systemie plików Windows montowany do Linuksa — sklonuj repo wewnątrz WSL (`\\wsl$`) |
| `backend` startuje przed bazą | `depends_on` z `condition: service_healthy` + healthcheck `pg_isready` w compose |
| `Invalid redirection URI` | brak `http://localhost:8080/...` w portalu Viessmann |
| Worker zużył budżet | `docker compose stop worker`; `VIESSMANN_MOCK=1` |
| Port 8080/5432 zajęty | zmienić `DEV_HTTP_PORT` / `DEV_DB_PORT` w `.env` |
