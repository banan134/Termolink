"""Create/update the RLS-restricted runtime DB role. Run as the owner (DJANGO_DB_ROLE=admin)."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Ensure the app DB role exists with the password and grants from settings (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.DB_ROLE != "admin":
            raise CommandError("run with DJANGO_DB_ROLE=admin (owner connection)")
        from apps.tenants.dbrole import ensure_app_role

        with connection.cursor() as cursor:
            created = ensure_app_role(cursor, connection.connection)
        verb = "created" if created else "updated"
        self.stdout.write(f"app DB role {settings.DB_APP_USER!r} {verb}")
