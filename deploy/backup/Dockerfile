# Nightly encrypted PostgreSQL backups (docs/11 §Backup): pg_dump -Fc → age → rclone (optional).
FROM postgres:16-alpine
RUN apk add --no-cache age rclone tzdata bash
COPY backup.sh restore.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh
# crond in the foreground; the schedule comes from BACKUP_SCHEDULE (default 02:00 daily)
CMD ["sh", "-c", "echo \"${BACKUP_SCHEDULE:-0 2 * * *} /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1\" > /etc/crontabs/root && echo 'backup: cron installed' && crond -f -l 2"]
