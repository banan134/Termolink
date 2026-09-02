from django.urls import path

from .api import (
    ProviderAccountDetailView,
    ProviderAccountListView,
    ProviderAuthorizeView,
    ProviderDiscoveredView,
    ProviderDiscoverView,
)

urlpatterns = [
    path(
        "tenants/<str:tenant_id>/provider-accounts",
        ProviderAccountListView.as_view(),
        name="provider-accounts",
    ),
    path(
        "tenants/<str:tenant_id>/provider-accounts/<str:provider>/authorize",
        ProviderAuthorizeView.as_view(),
        name="provider-authorize",
    ),
    path(
        "tenants/<str:tenant_id>/provider-accounts/<str:account_id>/discover",
        ProviderDiscoverView.as_view(),
        name="provider-discover",
    ),
    path(
        "tenants/<str:tenant_id>/provider-accounts/<str:account_id>/discovered",
        ProviderDiscoveredView.as_view(),
        name="provider-discovered",
    ),
    path(
        "tenants/<str:tenant_id>/provider-accounts/<str:account_id>",
        ProviderAccountDetailView.as_view(),
        name="provider-account",
    ),
]
