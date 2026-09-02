from django.urls import path

from .api import (
    DeviceDetailView,
    DeviceFeaturesView,
    DeviceHistoryView,
    DeviceListView,
    DeviceRefreshView,
    DeviceStatusHistoryView,
)

urlpatterns = [
    path("tenants/<str:tenant_id>/devices", DeviceListView.as_view(), name="devices"),
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>", DeviceDetailView.as_view(), name="device"
    ),
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>/refresh",
        DeviceRefreshView.as_view(),
        name="device-refresh",
    ),
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>/features",
        DeviceFeaturesView.as_view(),
        name="device-features",
    ),
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>/history",
        DeviceHistoryView.as_view(),
        name="device-history",
    ),
    path(
        "tenants/<str:tenant_id>/devices/<str:device_id>/status-history",
        DeviceStatusHistoryView.as_view(),
        name="device-status-history",
    ),
]
