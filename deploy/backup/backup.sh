#!/usr/bin/env bash
# pg_dump -Fc → age (public-key encryption) → local /backups + optional rclone remote.
# Env (deploy/.env): POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, BACKUP_AGE_RECIPIENT (age1…),
#   BACKUP_RETENTION_DAYS (default 30), RCLONE_REMOTE (e.g. "b2:termolink-backups", optional),
#   ALERT_EMAIL_OPERATOR + SMTP_URL are NOT used here — failures are reported through the exit code
#   and the marker file /backups/LAST_STATUS, which the worker reads (alert `backup_failed`).
set -euo pipefail

: "${PGHOST:=db}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_RETENTION_DAYS:=30}"
export PGPASSWORD="$POSTGRES_PASSWORD"

stamp="$(date -u +%Y%m%d-%H%M%S)"
dir=/backups
tmp="$dir/.tmp-$stamp.dump"
out="$dir/termolink-$stamp.dump"
status="$dir/LAST_STATUS"

fail() { echo "backup FAILED: $*" >&2; echo "failed $(date -u +%FT%TZ) $*" > "$status"; exit 1; }

echo "backup: starting $stamp"
pg_dump -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner -f "$tmp" || fail "pg_dump"

if [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  age -r "$BACKUP_AGE_RECIPIENT" -o "$out.age" "$tmp" || fail "age"
  rm -f "$tmp"
  out="$out.age"
else
  echo "backup: WARNING — BACKUP_AGE_RECIPIENT not set, dump stored unencrypted"
  mv "$tmp" "$out"
fi
size=$(stat -c %s "$out")
echo "backup: wrote $out ($size bytes)"

if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$out" "$RCLONE_REMOTE/" --quiet || fail "rclone copy"
  # remote retention: 30 daily + keep the first dump of each month for 12 months
  rclone delete "$RCLONE_REMOTE/" --min-age "${BACKUP_RETENTION_DAYS}d" --exclude "*-01-0*" --quiet || true
  echo "backup: copied to $RCLONE_REMOTE"
fi

find "$dir" -name 'termolink-*.dump*' -mtime +"$BACKUP_RETENTION_DAYS" -delete
echo "ok $(date -u +%FT%TZ) $out $size" > "$status"
echo "backup: done"
