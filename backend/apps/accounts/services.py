"""Auth services (docs/04 §Auth, docs/08). Views call these; no business logic in views."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from apps.core.exceptions import ApiError
from apps.tenants.context import system_context

from .models import LoginAttempt, User, UserSession

LOGIN_AT_KEY = "login_at"


def client_ip(request: HttpRequest) -> str | None:
    """First X-Forwarded-For hop (set by our Caddy) or the peer address."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


# --- lockout ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lockout:
    retry_after_s: int


def lockout_for(email: str, ip: str | None) -> Lockout | None:
    """Escalating delay after >= threshold failures (per account or per IP) in the window."""
    now = timezone.now()
    window_start = now - timedelta(seconds=settings.LOGIN_LOCKOUT_WINDOW_S)
    scope = Q(email_lower=email.lower())
    if ip:
        scope |= Q(ip=ip)
    failures = list(
        LoginAttempt.objects.filter(scope, success=False, ts__gte=window_start)
        .order_by("-ts")
        .values_list("ts", flat=True)[: settings.LOGIN_LOCKOUT_THRESHOLD + 32]
    )
    over = len(failures) - settings.LOGIN_LOCKOUT_THRESHOLD
    if over < 0:
        return None
    delay = min(60 * (2**over), settings.LOGIN_LOCKOUT_MAX_DELAY_S)
    retry_at = failures[0] + timedelta(seconds=delay)
    if retry_at <= now:
        return None
    return Lockout(retry_after_s=int((retry_at - now).total_seconds()) + 1)


def record_attempt(email: str, ip: str | None, *, success: bool) -> None:
    LoginAttempt.objects.create(email_lower=email.lower(), ip=ip, success=success)
    if success:
        LoginAttempt.objects.filter(email_lower=email.lower(), success=False).delete()


# --- login / logout --------------------------------------------------------------------------


def login_user(request: HttpRequest, *, email: str, password: str, totp: str | None) -> User:
    ip = client_ip(request)
    lock = lockout_for(email, ip)
    if lock:
        raise ApiError(
            "login_locked",
            "Zbyt wiele nieudanych prób logowania. Spróbuj ponownie później.",
            status_code=429,
            extra={"retry_after_s": lock.retry_after_s},
        )

    user = authenticate(request, username=email, password=password)
    if user is None or not user.is_active:
        record_attempt(email, ip, success=False)
        raise ApiError("invalid_credentials", "Nieprawidłowy e-mail lub hasło.", status_code=401)
    assert isinstance(user, User)

    if user.totp_enabled:
        # Code verification arrives with the TOTP endpoints (stage 1, task 6).
        raise ApiError(
            "totp_required", "Wymagany kod z aplikacji uwierzytelniającej.", status_code=428
        )
    if settings.REQUIRE_OPERATOR_TOTP and user.is_operator:
        raise ApiError(
            "totp_setup_required",
            "Konto operatora wymaga włączonego 2FA.",
            status_code=403,
        )

    record_attempt(email, ip, success=True)
    login(request, user)  # rotates the session key
    request.session[LOGIN_AT_KEY] = timezone.now().isoformat()
    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key
    assert session_key is not None
    UserSession.objects.create(
        session_key=session_key,
        user=user,
        tenant_id=user.tenant_id,
        ip=ip,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
    )
    return user


def logout_user(request: HttpRequest) -> None:
    key = request.session.session_key
    if key:
        UserSession.objects.filter(session_key=key).delete()
    logout(request)


# --- profile ---------------------------------------------------------------------------------


def me_payload(request: HttpRequest, user: User) -> dict[str, Any]:
    ctx = getattr(request, "tenant_context", None)
    allowed = [str(t) for t in ctx.allowed_tenants] if ctx else []
    tenant = None
    if user.tenant is not None:
        tenant = {"id": str(user.tenant.id), "name": user.tenant.name}
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "tenant": tenant,
        "totp_enabled": user.totp_enabled,
        "allowed_tenants": allowed,
        "ui_theme": user.ui_theme,
    }


def update_profile(user: User, *, ui_theme: str | None = None) -> User:
    if ui_theme is not None:
        user.ui_theme = ui_theme
        user.save(update_fields=["ui_theme"])
    return user


def change_password(request: HttpRequest, user: User, *, old: str, new: str) -> None:
    if not user.check_password(old):
        raise ApiError(
            "invalid_password",
            "Stare hasło jest nieprawidłowe.",
            status_code=400,
            fields={"old_password": ["Nieprawidłowe hasło."]},
        )
    user.set_password(new)
    user.save(update_fields=["password"])
    old_key = request.session.session_key
    update_session_auth_hash(request, user)  # keeps this session but rotates its key
    new_key = request.session.session_key
    if old_key and new_key and old_key != new_key:
        UserSession.objects.filter(session_key=old_key).update(session_key=new_key)
    revoke_other_sessions(user, keep_session_key=new_key)  # every other session is dropped


# --- sessions --------------------------------------------------------------------------------


def list_sessions(request: HttpRequest, user: User) -> list[dict[str, Any]]:
    current = request.session.session_key
    return [
        {
            "id": str(s.id),
            "ip": s.ip,
            "user_agent": s.user_agent,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "current": s.session_key == current,
        }
        for s in UserSession.objects.filter(user=user)
    ]


def revoke_session(request: HttpRequest, user: User, session_id: str) -> None:
    try:
        row = UserSession.objects.get(id=session_id, user=user)
    except (UserSession.DoesNotExist, ValueError) as exc:
        raise ApiError("not_found", "Sesja nie istnieje.", status_code=404) from exc
    if row.session_key == request.session.session_key:
        logout_user(request)
        return
    _delete_django_sessions([row.session_key])
    row.delete()


def revoke_other_sessions(user: User, *, keep_session_key: str | None) -> int:
    rows = UserSession.objects.filter(user=user).exclude(session_key=keep_session_key or "")
    keys = list(rows.values_list("session_key", flat=True))
    _delete_django_sessions(keys)
    deleted, _ = rows.delete()
    return deleted


def _delete_django_sessions(keys: list[str]) -> None:
    if keys:
        Session.objects.filter(session_key__in=keys).delete()


def touch_session(request: HttpRequest) -> None:
    """Update last_seen_at at most once a minute; drop sessions past the absolute max age."""
    key = request.session.session_key
    if not key:
        return
    login_at = request.session.get(LOGIN_AT_KEY)
    if login_at:
        started = datetime.fromisoformat(login_at)
        if timezone.now() - started > timedelta(seconds=settings.SESSION_ABSOLUTE_MAX_AGE):
            logout_user(request)
            return
    with system_context():
        UserSession.objects.filter(
            session_key=key, last_seen_at__lt=timezone.now() - timedelta(seconds=60)
        ).update(last_seen_at=timezone.now())
