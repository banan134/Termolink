"""Auth services (docs/04 §Auth, docs/08). Views call these; no business logic in views."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from apps.audit.services import audit
from apps.core.exceptions import ApiError
from apps.tenants.context import system_context

from . import emails, totp
from .models import (
    Invitation,
    LoginAttempt,
    PasswordResetToken,
    User,
    UserSession,
    hash_token,
)

LOGIN_AT_KEY = "login_at"
REAUTH_UNTIL_KEY = "reauth_until"
TOTP_PENDING_SECRET_KEY = "totp_pending_secret"  # noqa: S105 — session key name, not a secret
TOTP_SETUP_ALLOWED_PATHS = ("/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/totp/")


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


def login_user(request: HttpRequest, *, email: str, password: str, totp_code: str | None) -> User:
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
        audit(
            "auth.login.failed",
            request=request,
            details={"email": email.lower(), "reason": "invalid_credentials"},
        )
        raise ApiError("invalid_credentials", "Nieprawidłowy e-mail lub hasło.", status_code=401)
    assert isinstance(user, User)

    if user.totp_enabled:
        if not totp_code:
            raise ApiError(
                "totp_required", "Wymagany kod z aplikacji uwierzytelniającej.", status_code=428
            )
        if not _check_second_factor(user, totp_code):
            record_attempt(email, ip, success=False)
            audit(
                "auth.login.failed",
                request=request,
                user=user,
                details={"email": email.lower(), "reason": "invalid_totp"},
            )
            raise ApiError("invalid_totp", "Nieprawidłowy kod 2FA.", status_code=401)

    record_attempt(email, ip, success=True)
    _start_session(request, user)
    audit("auth.login", request=request, user=user, details={"totp": user.totp_enabled})
    return user


def _start_session(request: HttpRequest, user: User) -> None:
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
        ip=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
    )


def _check_second_factor(user: User, code: str) -> bool:
    """TOTP or backup code; persists consumed backup codes."""
    with system_context():
        ok = totp.verify_user_code(user, code)
        if ok:
            user.save(update_fields=["backup_codes_hash"])
    return ok


def totp_setup_pending(user: User) -> bool:
    """Operators must enable 2FA before doing anything else (docs/08)."""
    return bool(settings.REQUIRE_OPERATOR_TOTP and user.is_operator and not user.totp_enabled)


def logout_user(request: HttpRequest) -> None:
    key = request.session.session_key
    if key:
        UserSession.objects.filter(session_key=key).delete()
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        audit("auth.logout", request=request, user=user)
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
    dropped = revoke_other_sessions(user, keep_session_key=new_key)
    audit(
        "auth.password.changed", request=request, user=user, details={"sessions_revoked": dropped}
    )


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
    audit("auth.session.revoked", request=request, user=user, target=row)


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


# --- reauth ----------------------------------------------------------------------------------


def reauth(request: HttpRequest, user: User, *, password: str, totp_code: str | None) -> None:
    if not user.check_password(password):
        raise ApiError("invalid_credentials", "Nieprawidłowe hasło.", status_code=401)
    if user.totp_enabled:
        if not totp_code:
            raise ApiError(
                "totp_required", "Wymagany kod z aplikacji uwierzytelniającej.", status_code=428
            )
        if not _check_second_factor(user, totp_code):
            raise ApiError("invalid_totp", "Nieprawidłowy kod 2FA.", status_code=401)
    until = timezone.now() + timedelta(seconds=settings.REAUTH_TTL_S)
    request.session[REAUTH_UNTIL_KEY] = until.isoformat()
    audit("auth.reauth", request=request, user=user)


def has_valid_reauth(request: HttpRequest) -> bool:
    raw = request.session.get(REAUTH_UNTIL_KEY)
    if not raw:
        return False
    return datetime.fromisoformat(str(raw)) > timezone.now()


def require_reauth(request: HttpRequest) -> None:
    """Guard for sensitive operations (docs/08): 428 unless reauth happened in the last 5 min."""
    if not has_valid_reauth(request):
        raise ApiError(
            "reauth_required", "Potwierdź tożsamość hasłem (i kodem 2FA).", status_code=428
        )


# --- TOTP ------------------------------------------------------------------------------------


def totp_setup(request: HttpRequest, user: User) -> dict[str, str]:
    if user.totp_enabled:
        raise ApiError("totp_already_enabled", "2FA jest już włączone.", status_code=409)
    secret = totp.new_secret()
    request.session[TOTP_PENDING_SECRET_KEY] = secret
    return {"secret": secret, "otpauth_url": totp.otpauth_url(user, secret)}


def totp_enable(request: HttpRequest, user: User, *, code: str) -> list[str]:
    if user.totp_enabled:
        raise ApiError("totp_already_enabled", "2FA jest już włączone.", status_code=409)
    secret = request.session.get(TOTP_PENDING_SECRET_KEY)
    if not secret:
        raise ApiError("totp_setup_missing", "Najpierw wywołaj /auth/totp/setup.", status_code=409)
    if not totp.verify_code(secret, code):
        raise ApiError(
            "invalid_totp",
            "Nieprawidłowy kod. Sprawdź czas na telefonie.",
            status_code=400,
            fields={"code": ["Nieprawidłowy kod."]},
        )
    codes = totp.new_backup_codes()
    totp.store_secret(user, secret)
    user.backup_codes_hash = [totp.hash_backup_code(c) for c in codes]
    user.totp_enabled = True
    user.save(update_fields=["totp_secret_enc", "backup_codes_hash", "totp_enabled"])
    del request.session[TOTP_PENDING_SECRET_KEY]
    audit("auth.totp.enabled", request=request, user=user)
    return codes


def totp_disable(request: HttpRequest, user: User, *, password: str, code: str) -> None:
    if not user.totp_enabled:
        raise ApiError("totp_not_enabled", "2FA nie jest włączone.", status_code=409)
    if not user.check_password(password):
        raise ApiError("invalid_credentials", "Nieprawidłowe hasło.", status_code=401)
    if not _check_second_factor(user, code):
        raise ApiError("invalid_totp", "Nieprawidłowy kod 2FA.", status_code=401)
    if settings.REQUIRE_OPERATOR_TOTP and user.is_operator:
        raise ApiError("totp_required_for_role", "Operator nie może wyłączyć 2FA.", status_code=403)
    user.totp_secret_enc = None
    user.backup_codes_hash = None
    user.totp_enabled = False
    user.save(update_fields=["totp_secret_enc", "backup_codes_hash", "totp_enabled"])
    request.session.pop(REAUTH_UNTIL_KEY, None)
    audit("auth.totp.disabled", request=request, user=user)


# --- password reset --------------------------------------------------------------------------


def request_password_reset(email: str) -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    with system_context():
        user = User.objects.filter(email=email.lower(), is_active=True).first()
        if user is None:
            return
        token = secrets.token_urlsafe(32)
        PasswordResetToken.objects.create(
            user=user,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TTL_S),
        )
    emails.send_password_reset(user.email, token)
    audit("auth.password.reset_requested", user=user)


def reset_password(*, token: str, new_password: str) -> User:
    with system_context():
        row = (
            PasswordResetToken.objects.select_related("user")
            .filter(token_hash=hash_token(token))
            .first()
        )
        if row is None or not row.is_valid:
            raise ApiError("invalid_token", "Link jest nieprawidłowy lub wygasł.", status_code=400)
        user = row.user
        user.set_password(new_password)
        user.save(update_fields=["password"])
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        dropped = revoke_other_sessions(user, keep_session_key=None)
    audit("auth.password.reset", user=user, details={"sessions_revoked": dropped})
    return user


# --- invitations -----------------------------------------------------------------------------


def issue_invitation(
    *, email: str, role: str, tenant: Any | None, created_by: User | None
) -> Invitation:
    """Create + e-mail an invitation. Used by the operator/tenant-admin APIs (docs/04)."""
    invitation, token = Invitation.issue(
        email=email, role=role, tenant=tenant, created_by=created_by
    )
    emails.send_invitation(
        invitation.email, token, tenant_name=tenant.name if tenant is not None else None
    )
    audit(
        "auth.invitation.issued",
        user=created_by,
        tenant=tenant,
        target=invitation,
        details={"email": invitation.email, "role": role},
    )
    return invitation


def accept_invitation(request: HttpRequest, *, token: str, password: str) -> User:
    with system_context():
        invitation = (
            Invitation.objects.select_related("tenant").filter(token_hash=hash_token(token)).first()
        )
        if invitation is None or not invitation.is_valid:
            raise ApiError(
                "invalid_token", "Zaproszenie jest nieprawidłowe lub wygasło.", status_code=400
            )
        if User.objects.filter(email=invitation.email).exists():
            raise ApiError("email_taken", "Konto z tym adresem już istnieje.", status_code=409)
        user = User.objects.create_user(
            invitation.email, password, role=invitation.role, tenant=invitation.tenant
        )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
    _start_session(request, user)
    audit("auth.invitation.accepted", request=request, user=user, target=invitation)
    return user
