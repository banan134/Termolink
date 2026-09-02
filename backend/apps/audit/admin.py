from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "action", "user", "tenant", "target_type", "target_id", "ip")
    list_filter = ("action",)
    search_fields = ("action", "target_type")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False
