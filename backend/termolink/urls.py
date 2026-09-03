from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.providers.api import oauth_callback

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.ingest.urls")),
    path("api/v1/", include("apps.tenants.urls")),
    path("api/v1/", include("apps.providers.urls")),
    path("api/v1/", include("apps.devices.urls")),
    path("api/v1/", include("apps.control.urls")),
    path("api/v1/", include("apps.alerts.urls")),
    path("api/v1/", include("apps.reports.urls")),
    path("oauth/<str:provider>/callback", oauth_callback, name="oauth-callback"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

# Django admin: dev only; on prod it sits behind Caddy basic-auth for the superadmin (docs/11).
if settings.DJANGO_ENV == "dev" or settings.DEBUG:
    urlpatterns.append(path("admin-django/", admin.site.urls))
