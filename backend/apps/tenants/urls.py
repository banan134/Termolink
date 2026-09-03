from django.urls import path

from .api import (
    AdminTechniciansView,
    AdminTenantDetailView,
    AdminTenantInvitationsView,
    AdminTenantListView,
    AdminTenantLogoView,
    AdminTenantUsersView,
    TechnicianMembershipDetailView,
    TechnicianMembershipsView,
    TenantInvitationsView,
    TenantUsersView,
)

urlpatterns = [
    path(
        "admin/tenants/<str:tenant_id>/logo",
        AdminTenantLogoView.as_view(),
        name="admin-tenant-logo",
    ),
    path("admin/tenants", AdminTenantListView.as_view(), name="admin-tenants"),
    path("admin/tenants/<str:tenant_id>", AdminTenantDetailView.as_view(), name="admin-tenant"),
    path(
        "admin/tenants/<str:tenant_id>/users",
        AdminTenantUsersView.as_view(),
        name="admin-tenant-users",
    ),
    path(
        "admin/tenants/<str:tenant_id>/invitations",
        AdminTenantInvitationsView.as_view(),
        name="admin-tenant-invitations",
    ),
    path("admin/technicians", AdminTechniciansView.as_view(), name="admin-technicians"),
    path(
        "admin/technicians/<str:user_id>/memberships",
        TechnicianMembershipsView.as_view(),
        name="admin-technician-memberships",
    ),
    path(
        "admin/technicians/<str:user_id>/memberships/<str:tenant_id>",
        TechnicianMembershipDetailView.as_view(),
        name="admin-technician-membership",
    ),
    # tenant_admin (and operators) — docs/14 B7
    path("tenants/<str:tenant_id>/users", TenantUsersView.as_view(), name="tenant-users"),
    path(
        "tenants/<str:tenant_id>/invitations",
        TenantInvitationsView.as_view(),
        name="tenant-invitations",
    ),
]
