from django.urls import path

from .api import CommandConfirmView, CommandDetailView, CommandListView, DeviceCommandsView

urlpatterns = [
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>/commands",
        DeviceCommandsView.as_view(),
        name="device-commands",
    ),
    path("tenants/<str:tenant_id>/commands", CommandListView.as_view(), name="commands"),
    path(
        "tenants/<str:tenant_id>/commands/<str:command_id>",
        CommandDetailView.as_view(),
        name="command",
    ),
    path(
        "tenants/<str:tenant_id>/commands/<str:command_id>/confirm",
        CommandConfirmView.as_view(),
        name="command-confirm",
    ),
]
