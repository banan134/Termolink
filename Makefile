# Termolink — developer shortcuts (see docs/15-local-development.md).
# Everything runs in Docker; nothing is installed on the host.

COMPOSE := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml
ENV_FILE := deploy/.env

.PHONY: dev up down reset migrate makemigrations seed test lint shell psql logs worker env

env: $(ENV_FILE)

$(ENV_FILE):
	cp deploy/.env.example $(ENV_FILE)
	@echo "Created $(ENV_FILE) from .env.example — fill in VIESSMANN_CLIENT_ID when needed."

dev: env
	$(COMPOSE) up --build

up: env
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

# Schema changes run as the DB owner; the app itself uses the RLS-restricted role (docs/03).
migrate:
	$(COMPOSE) exec -e DJANGO_DB_ROLE=admin backend python manage.py migrate

makemigrations:
	$(COMPOSE) exec -e DJANGO_DB_ROLE=admin backend python manage.py makemigrations

seed:
	$(COMPOSE) exec backend python manage.py seed_demo

test:
	$(COMPOSE) exec backend pytest
	$(COMPOSE) exec frontend npm test -- --run

lint:
	$(COMPOSE) exec backend ruff check .
	$(COMPOSE) exec backend ruff format --check .
	$(COMPOSE) exec backend mypy .
	$(COMPOSE) exec frontend npm run lint
	$(COMPOSE) exec frontend npm run typecheck

shell:
	$(COMPOSE) exec -e DJANGO_DB_ROLE=admin backend python manage.py shell

psql:
	$(COMPOSE) exec db psql -U termolink

# usage: make logs s=worker
logs:
	$(COMPOSE) logs -f $(s)

worker:
	$(COMPOSE) exec backend python manage.py run_worker --once

# --- production (VPS) — ops/runbook.md ---
PROD = docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml

prod-up:           ## pull images (IMAGE_TAG from deploy/.env) and (re)start everything
	$(PROD) pull && $(PROD) up -d

prod-ps:
	$(PROD) ps

prod-logs:
	$(PROD) logs -f --tail 200 backend worker caddy

backup-now:        ## run one encrypted pg_dump immediately
	$(PROD) exec backup backup.sh

restore:           ## make restore FILE=/backups/termolink-....dump.age AGE_SECRET_KEY=AGE-SECRET-KEY-1...
	$(PROD) stop backend worker caddy
	$(PROD) run --rm -e AGE_SECRET_KEY="$(AGE_SECRET_KEY)" backup restore.sh "$(FILE)"
	$(PROD) up -d
