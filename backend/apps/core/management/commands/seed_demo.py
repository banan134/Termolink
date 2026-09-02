"""`manage.py seed_demo` — demo data for dev/staging (docs/12 §Dane testowe, docs/15).

Refuses to run unless DJANGO_ENV=dev. Idempotent: re-running updates passwords and keeps
existing TOTP secrets. Devices, fixtures and synthetic history arrive in stage 2.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import totp
from apps.accounts.models import Role, User
from apps.tenants.context import system_context
from apps.tenants.models import Tenant, TenantMembership

DEMO_TENANTS = [
    {"name": "Wspólnota Mieszkaniowa Jeziorna 12", "type": "company", "slug": "jeziorna"},
    {"name": "Jan Nowak — dom Olsztyn", "type": "person", "slug": "nowak"},
]
OPERATOR_EMAIL = "admin@termolink.local"
TECHNICIAN_EMAIL = "serwis@termolink.local"


class Command(BaseCommand):
    help = "Create demo operator, technician and two demo tenants (dev only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.DJANGO_ENV != "dev":
            raise CommandError("seed_demo runs only with DJANGO_ENV=dev")
        password: str = getattr(settings, "DEV_ADMIN_PASSWORD", "") or ""
        if len(password) < 12:
            raise CommandError("set DEV_ADMIN_PASSWORD (>= 12 chars) in deploy/.env")

        with transaction.atomic(), system_context():
            admin, admin_created = self._user(OPERATOR_EMAIL, password, Role.SUPERADMIN, None)
            tech, _ = self._user(TECHNICIAN_EMAIL, password, Role.TECHNICIAN, None)
            tenants = []
            for spec in DEMO_TENANTS:
                tenant, _ = Tenant.objects.get_or_create(
                    name=spec["name"], defaults={"type": spec["type"]}
                )
                tenants.append(tenant)
                self._user(f"admin@{spec['slug']}.demo", password, Role.TENANT_ADMIN, tenant)
                self._user(f"user@{spec['slug']}.demo", password, Role.TENANT_USER, tenant)
            TenantMembership.objects.get_or_create(
                user=tech, tenant=tenants[0], defaults={"can_control": True}
            )
            secrets = {u: self._ensure_totp(u) for u in (admin, tech)}

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  password for every account: {password}")
        for user, secret in secrets.items():
            if secret:
                self.stdout.write(
                    f"  {user.email}: NEW TOTP secret {secret}\n"
                    f"    {totp.otpauth_url(user, secret)}"
                )
            else:
                self.stdout.write(f"  {user.email}: TOTP already enabled (secret unchanged)")
        for spec in DEMO_TENANTS:
            self.stdout.write(
                f"  {spec['name']}: admin@{spec['slug']}.demo, user@{spec['slug']}.demo"
            )

    @staticmethod
    def _user(email: str, password: str, role: str, tenant: Tenant | None) -> tuple[User, bool]:
        user = User.objects.filter(email=email).first()
        if user is None:
            return User.objects.create_user(email, password, role=role, tenant=tenant), True
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        return user, False

    @staticmethod
    def _ensure_totp(user: User) -> str | None:
        """Operators are gated until 2FA is on; provision it so dev can log in right away."""
        if user.totp_enabled:
            return None
        secret = totp.new_secret()
        totp.store_secret(user, secret)
        user.backup_codes_hash = [totp.hash_backup_code(c) for c in totp.new_backup_codes()]
        user.totp_enabled = True
        user.save(update_fields=["totp_secret_enc", "backup_codes_hash", "totp_enabled"])
        return secret
