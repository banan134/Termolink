"""Core API views. Views hold no business logic (docs/02)."""

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

WORKER_STALE_AFTER = timedelta(minutes=2)


def worker_alive() -> bool | None:
    """True/False when heartbeats exist, None when no worker has ever registered."""
    from apps.ingest.models import WorkerHeartbeat

    last = (
        WorkerHeartbeat.objects.order_by("-last_beat_at")
        .values_list("last_beat_at", flat=True)
        .first()
    )
    if last is None:
        return None
    return timezone.now() - last <= WORKER_STALE_AFTER


def backup_status() -> str | None:
    """Content of the backup marker written by deploy/backup/backup.sh, if mounted."""
    path = Path(settings.BACKUP_STATUS_FILE)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()[:200]
    except OSError:
        return None


class HealthView(APIView):
    """Liveness/readiness probe for the external uptime check (docs/11 §Monitoring):
    503 when the database does not answer or no worker has reported for 2 minutes."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer(
            name="Health",
            fields={
                "status": serializers.CharField(),
                "db": serializers.BooleanField(),
                "worker": serializers.BooleanField(allow_null=True),
                "backup": serializers.CharField(allow_null=True),
            },
        ),
        auth=[],
    )
    def get(self, request: Request) -> Response:
        db_ok = True
        worker: bool | None = None
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            worker = worker_alive()
        except DatabaseError:
            db_ok = False
        backup = backup_status()
        healthy = db_ok and worker is not False and not (backup or "").startswith("failed")
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "db": db_ok,
                "worker": worker,
                "backup": backup,
            },
            status=200 if healthy else 503,
        )
