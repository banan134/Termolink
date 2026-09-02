from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Invitation, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "role", "tenant", "totp_enabled", "is_active")
    list_filter = ("role", "is_active", "totp_enabled")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Rola", {"fields": ("role", "tenant", "is_active")}),
        ("2FA", {"fields": ("totp_enabled",)}),
        ("Preferencje", {"fields": ("ui_theme",)}),
        ("Daty", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "role", "tenant", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("last_login", "created_at")
    filter_horizontal = ()


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "tenant", "expires_at", "accepted_at")
    readonly_fields = ("token_hash",)
