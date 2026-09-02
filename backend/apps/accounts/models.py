"""Users, roles and invitations — docs/00 (roles), docs/03 (tables), docs/08 (auth)."""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

INVITATION_TTL = timedelta(hours=72)


class Role(models.TextChoices):
    SUPERADMIN = "superadmin", "Superadmin"
    TECHNICIAN = "technician", "Serwisant"
    TENANT_ADMIN = "tenant_admin", "Administrator klienta"
    TENANT_USER = "tenant_user", "Użytkownik klienta"


OPERATOR_ROLES: frozenset[str] = frozenset({Role.SUPERADMIN, Role.TECHNICIAN})
TENANT_ROLES: frozenset[str] = frozenset({Role.TENANT_ADMIN, Role.TENANT_USER})
# Sorted for deterministic migrations (set iteration order varies between processes).
_OPERATOR_ROLE_LIST = sorted(OPERATOR_ROLES)
_TENANT_ROLE_LIST = sorted(TENANT_ROLES)


class UiTheme(models.TextChoices):
    LIGHT = "light", "Jasny"
    DARK = "dark", "Ciemny"


class UserManager(BaseUserManager["User"]):
    def create_user(self, email: str, password: str | None = None, **extra: Any) -> "User":
        if not email:
            raise ValueError("email is required")
        extra.setdefault("role", Role.TENANT_USER)
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> "User":
        extra["role"] = Role.SUPERADMIN
        extra["tenant"] = None
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Portal user.

    Operators (superadmin/technician) have tenant=NULL; customer users must have a tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    email = models.EmailField(max_length=254)
    role = models.TextField(choices=Role.choices)
    totp_secret_enc = models.BinaryField(null=True, blank=True)
    totp_enabled = models.BooleanField(default=False)
    backup_codes_hash = ArrayField(models.TextField(), null=True, blank=True)
    is_active = models.BooleanField(default=True)
    ui_theme = models.TextField(choices=UiTheme.choices, default=UiTheme.LIGHT)
    created_at = models.DateTimeField(auto_now_add=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(Lower("email"), name="users_email_ci_unique"),
            # role IN ('superadmin','technician') ⇔ tenant_id IS NULL (docs/03)
            models.CheckConstraint(
                condition=(
                    Q(role__in=_OPERATOR_ROLE_LIST, tenant__isnull=True)
                    | Q(role__in=_TENANT_ROLE_LIST, tenant__isnull=False)
                ),
                name="users_role_tenant_consistency",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_operator(self) -> bool:
        return self.role in OPERATOR_ROLES

    # Django admin (dev only, docs/11) is reachable by superadmins only.
    @property
    def is_staff(self) -> bool:
        return self.role == Role.SUPERADMIN

    @property
    def is_superuser(self) -> bool:  # type: ignore[override]
        return self.role == Role.SUPERADMIN

    def clean(self) -> None:
        super().clean()
        self.email = self.email.lower()
        if self.is_operator and self.tenant_id is not None:
            raise ValueError("operator roles must not belong to a tenant")
        if not self.is_operator and self.tenant_id is None:
            raise ValueError("tenant roles require a tenant")


def hash_token(token: str) -> str:
    """Tokens are stored hashed (docs/08): SHA-256 is enough for 256-bit random secrets."""
    return hashlib.sha256(token.encode()).hexdigest()


class Invitation(models.Model):
    """Single-use, 72 h invitation (docs/08). The raw token is only ever sent by e-mail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField(max_length=254)
    role = models.TextField(choices=Role.choices)
    token_hash = models.TextField(unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="sent_invitations"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invitations"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role__in=_OPERATOR_ROLE_LIST, tenant__isnull=True)
                    | Q(role__in=_TENANT_ROLE_LIST, tenant__isnull=False)
                ),
                name="invitations_role_tenant_consistency",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.role})"

    @classmethod
    def issue(
        cls, *, email: str, role: str, tenant: Any | None, created_by: User | None
    ) -> tuple["Invitation", str]:
        """Create an invitation and return it with the raw token (to be e-mailed, never stored)."""
        token = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            email=email.lower(),
            role=role,
            tenant=tenant,
            token_hash=hash_token(token),
            expires_at=timezone.now() + INVITATION_TTL,
            created_by=created_by,
        )
        return invitation, token

    @property
    def is_valid(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()


class LoginAttempt(models.Model):
    """Failed/successful login attempts for lockout (docs/08). No tenant_id: pre-auth data."""

    email_lower = models.TextField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField(default=False)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "login_attempts"
        indexes = [
            models.Index(fields=["email_lower", "ts"], name="login_attempts_email_ts"),
            models.Index(fields=["ip", "ts"], name="login_attempts_ip_ts"),
        ]

    def __str__(self) -> str:
        return f"{self.email_lower} {'ok' if self.success else 'fail'} {self.ts:%Y-%m-%d %H:%M}"


class UserSession(models.Model):
    """One row per active Django session, so users can list and revoke their sessions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.TextField(unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_sessions"
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return f"{self.user_id} {self.ip} {self.created_at:%Y-%m-%d}"
