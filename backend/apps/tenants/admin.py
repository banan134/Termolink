from django.contrib import admin

from .models import Tenant, TenantMembership


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin[Tenant]):
    list_display = ("name", "type", "control_allowed", "timezone", "archived_at")
    search_fields = ("name",)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin[TenantMembership]):
    list_display = ("user", "tenant", "can_control")
