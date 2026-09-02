# Termolink

Wielodostępowy portal monitoringu i sterowania urządzeniami grzewczymi (start: Viessmann).
Dokumentacja projektu — źródło prawdy — jest w [`docs/`](docs/00-overview.md); zasady pracy
w [`CLAUDE.md`](CLAUDE.md).

## Uruchomienie lokalne

Wymagany jest tylko Docker (Desktop lub Engine + Compose v2). Szczegóły: [`docs/15-local-development.md`](docs/15-local-development.md).

```bash
git clone https://github.com/banan134/termolink.git && cd termolink
make dev        # tworzy deploy/.env z .env.example przy pierwszym uruchomieniu
```

Bez `make` (np. Windows bez WSL):

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
```

| Adres | Co |
|---|---|
| http://localhost:8080 | aplikacja (Caddy → frontend Vite + `/api` → Django) |
| http://localhost:8080/api/v1/health | stan backendu i bazy |
| http://localhost:8080/api/schema/swagger/ | OpenAPI |
| http://localhost:8080/admin-django/ | panel Django (tylko dev) |
| http://localhost:8025 | Mailpit — wysłane e-maile |
| localhost:5432 | PostgreSQL + TimescaleDB (`termolink` / hasło z `deploy/.env`) |

## Stan prac

Etap 1 (fundament) z [`docs/13-roadmap.md`](docs/13-roadmap.md) — zadanie 1: szkielet repozytorium.
`run_worker` jest na razie pustą pętlą z heartbeatem w logu; kolejka `jobs` i heartbeat w bazie
powstaną w zadaniu 8. `make seed` (`seed_demo`) — zadanie 9.
