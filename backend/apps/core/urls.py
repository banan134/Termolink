from django.urls import path

from .api import HealthView
from .settings_api import MailSettingsView, MailTestView

urlpatterns = [
    path("admin/settings/mail", MailSettingsView.as_view(), name="admin-settings-mail"),
    path("admin/settings/mail/test", MailTestView.as_view(), name="admin-settings-mail-test"),
    path("health", HealthView.as_view(), name="health"),
]
