from django.urls import path

from .api import (
    InvitationAcceptView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetRequestView,
    PasswordResetView,
    ReauthView,
    SessionDetailView,
    SessionListView,
    TotpDisableView,
    TotpEnableView,
    TotpSetupView,
)

urlpatterns = [
    path("login", LoginView.as_view(), name="auth-login"),
    path("logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="auth-me"),
    path("password/change", PasswordChangeView.as_view(), name="auth-password-change"),
    path("password/reset-request", PasswordResetRequestView.as_view(), name="auth-reset-request"),
    path("password/reset", PasswordResetView.as_view(), name="auth-reset"),
    path("reauth", ReauthView.as_view(), name="auth-reauth"),
    path("totp/setup", TotpSetupView.as_view(), name="auth-totp-setup"),
    path("totp/enable", TotpEnableView.as_view(), name="auth-totp-enable"),
    path("totp/disable", TotpDisableView.as_view(), name="auth-totp-disable"),
    path("invitations/accept", InvitationAcceptView.as_view(), name="auth-invitation-accept"),
    path("sessions", SessionListView.as_view(), name="auth-sessions"),
    path("sessions/<str:session_id>", SessionDetailView.as_view(), name="auth-session-detail"),
]
