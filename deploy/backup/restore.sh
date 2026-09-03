#!/usr/bin/env bash
# Restore a backup into the running db service (ops/runbook.md §Przywracanie).
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
#     -e AGE_SECRET_KEY="AGE-SECRET-KEY-1…" backup restore.sh /backups/termolink-YYYYMMDD-HHMMSS.dump.age
# Stops nothing by itself: stop backend/worker first, run, then start them again.
set -euo pipefail

file="${1:?usage: restore.sh <file.dump|file.dump.age>}"
: "${PGHOST:=db}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
export PGPASSWORD="$POSTGRES_PASSWORD"

dump="$file"
if [[ "$file" == *.age ]]; then
  : "${AGE_SECRET_KEY:?AGE_SECRET_KEY (the private key) is required for .age files}"
  dump="/tmp/restore.dump"
  echo "$AGE_SECRET_KEY" > /tmp/age.key
  age -d -i /tmp/age.key -o "$dump" "$file"
  rm -f /tmp/age.key
fi

echo "restore: dropping and recreating $POSTGRES_DB"
psql -h "$PGHOST" -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$POSTGRES_DB";
CREATE DATABASE "$POSTGRES_DB" OWNER "$POSTGRES_USER";
SQL
# Timescale: extension objects come from the dump; pre-create so the restore hook is active.
psql -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
psql -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_pre_restore();"
pg_restore -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges "$dump"
psql -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_post_restore();"
echo "restore: done — now run migrate + ensure_app_db_role (the app role and grants are recreated)"
