"""Tenants (customers) and technician memberships — docs/03-data-model.md."""

import uuid

from django.conf import settings
from django.db import models


class TenantType(models.TextChoices):
    COMPANY = "company", "Firma"
    PERSON = "person", "Osoba"


class Tenant(models.Model):
    """A customer: the data-isolation boundary. Every customer-owned row carries tenant_id."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    type = models.TextField(choices=TenantType.choices, default=TenantType.COMPANY)
    control_allowed = models.BooleanField(default=True)  # operator can block control globally
    logo_path = models.TextField(null=True, blank=True)  # noqa: DJ001 — NULL = no logo (docs/03)
    report_header_text = models.TextField(null=True, blank=True)  # noqa: DJ001 — docs/03
    timezone = models.TextField(default="Europe/Warsaw")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenants"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class TenantMembership(models.Model):
    """Technician ↔ tenant assignment. `can_control` gates command execution (docs/07)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    can_control = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_memberships"
        constraints = [
            models.UniqueConstraint(fields=["user", "tenant"], name="tenant_memberships_pk"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.tenant_id}"
