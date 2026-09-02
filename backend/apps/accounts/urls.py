from django.urls import path

from .api import (
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    SessionDetailView,
    SessionListView,
)

urlpatterns = [
    path("login", LoginView.as_view(), name="auth-login"),
    path("logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="auth-me"),
    path("password/change", PasswordChangeView.as_view(), name="auth-password-change"),
    path("sessions", SessionListView.as_view(), name="auth-sessions"),
    path("sessions/<str:session_id>", SessionDetailView.as_view(), name="auth-session-detail"),
]
