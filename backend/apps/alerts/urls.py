from django.urls import path

from .api import AdminAlertsView, AlertDetailView, AlertListView, RuleDetailView, RuleListView

urlpatterns = [
    path("tenants/<str:tenant_id>/alerts", AlertListView.as_view(), name="alerts"),
    path("tenants/<str:tenant_id>/alerts/<str:alert_id>", AlertDetailView.as_view(), name="alert"),
    path("tenants/<str:tenant_id>/alert-rules", RuleListView.as_view(), name="alert-rules"),
    path(
        "tenants/<str:tenant_id>/alert-rules/<str:rule_id>",
        RuleDetailView.as_view(),
        name="alert-rule",
    ),
    path("admin/alerts", AdminAlertsView.as_view(), name="admin-alerts"),
]
