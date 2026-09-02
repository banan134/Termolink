"""Auth API part 2: TOTP, reauth, password reset, invitations (docs/12 §Auth)."""

import re
from datetime import datetime, timedelta
from typing import Any

import pyotp
import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.accounts.api import LoginThrottle
from apps.accounts.models import Invitation, PasswordResetToken, Role, User, UserSession
from apps.accounts.services import REAUTH_UNTIL_KEY
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "another-long-passphrase-42"
AUTH = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _isolated_throttle_cache() -> None:
    cache.clear()


@pytest.fixture
def no_login_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoginThrottle, "THROTTLE_RATES", {"login": "1000/min"})


def body_of(index: int) -> str:
    return str(mail.outbox[index].body)


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Klient A")


@pytest.fixture
def user(tenant: Tenant) -> User:
    return User.objects.create_user(
        "jan@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )


def post(client: Client, path: str, body: dict[str, Any]) -> Any:
    return client.post(f"{AUTH}{path}", body, content_type="application/json")


def login(client: Client, email: str, password: str = PASSWORD, totp: str | None = None) -> Any:
    body: dict[str, Any] = {"email": email, "password": password}
    if totp:
        body["totp"] = totp
    return post(client, "/login", body)


def enable_totp(client: Client) -> tuple[str, list[str]]:
    setup = post(client, "/totp/setup", {}).json()
    code = pyotp.TOTP(setup["secret"]).now()
    codes = post(client, "/totp/enable", {"code": code}).json()["backup_codes"]
    return setup["secret"], codes


# --- TOTP ------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_totp_setup_enable_login_and_backup_codes(
    client: Client, user: User, no_login_throttle: None
) -> None:
    assert login(client, user.email).status_code == 200
    setup = post(client, "/totp/setup", {})
    assert setup.status_code == 200
    assert setup.json()["otpauth_url"].startswith("otpauth://totp/Termolink:jan%40example.com")
    secret = setup.json()["secret"]

    bad = post(client, "/totp/enable", {"code": "000000"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_totp"

    ok = post(client, "/totp/enable", {"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    codes = ok.json()["backup_codes"]
    assert len(codes) == 10 and all(re.fullmatch(r"[0-9a-f]{10}", c) for c in codes)
    user.refresh_from_db()
    assert (
        user.totp_enabled
        and user.totp_secret_enc
        and secret.encode() not in bytes(user.totp_secret_enc)
    )
    assert client.get(f"{AUTH}/me").json()["totp_enabled"] is True

    # login now needs the second factor
    fresh = Client()
    assert login(fresh, user.email).status_code == 428
    wrong = login(fresh, user.email, totp="123456")
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_totp"
    assert login(fresh, user.email, totp=pyotp.TOTP(secret).now()).status_code == 200

    # a backup code works once
    another = Client()
    assert login(another, user.email, totp=codes[0]).status_code == 200
    user.refresh_from_db()
    assert len(user.backup_codes_hash or []) == 9
    assert login(Client(), user.email, totp=codes[0]).status_code == 401


@pytest.mark.django_db
def test_totp_disable_requires_password_and_code(client: Client, user: User) -> None:
    login(client, user.email)
    secret, _ = enable_totp(client)
    assert post(client, "/totp/disable", {"password": "x", "code": "1"}).status_code == 401
    assert (
        post(client, "/totp/disable", {"password": PASSWORD, "code": "000000"}).status_code == 401
    )
    ok = post(client, "/totp/disable", {"password": PASSWORD, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 204
    user.refresh_from_db()
    assert not user.totp_enabled and user.totp_secret_enc is None


@pytest.mark.django_db
def test_operator_without_totp_is_gated_until_setup(client: Client, tenant: Tenant) -> None:
    User.objects.create_superuser("admin@example.com", PASSWORD)
    assert login(client, "admin@example.com").status_code == 200
    blocked = client.get(f"{AUTH}/sessions")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "totp_setup_required"
    assert client.get(f"{AUTH}/me").status_code == 200  # allowed while setting up
    secret, _ = enable_totp(client)
    assert client.get(f"{AUTH}/sessions").status_code == 200
    # operators cannot switch 2FA off again
    off = post(client, "/totp/disable", {"password": PASSWORD, "code": pyotp.TOTP(secret).now()})
    assert off.status_code == 403 and off.json()["error"]["code"] == "totp_required_for_role"


# --- reauth ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_reauth_sets_short_lived_marker(client: Client, user: User) -> None:
    login(client, user.email)
    assert post(client, "/reauth", {"password": "nope"}).status_code == 401
    assert post(client, "/reauth", {"password": PASSWORD}).status_code == 204
    until = datetime.fromisoformat(client.session[REAUTH_UNTIL_KEY])
    assert timedelta(minutes=4) < until - timezone.now() <= timedelta(minutes=5)

    from django.test import RequestFactory

    from apps.accounts.services import has_valid_reauth, require_reauth
    from apps.core.exceptions import ApiError

    request = RequestFactory().get("/")
    request.session = client.session
    assert has_valid_reauth(request)
    request.session[REAUTH_UNTIL_KEY] = (timezone.now() - timedelta(seconds=1)).isoformat()
    with pytest.raises(ApiError) as exc:
        require_reauth(request)
    assert exc.value.status_code == 428


@pytest.mark.django_db
def test_reauth_requires_totp_when_enabled(client: Client, user: User) -> None:
    login(client, user.email)
    secret, _ = enable_totp(client)
    assert post(client, "/reauth", {"password": PASSWORD}).status_code == 428
    assert (
        post(
            client, "/reauth", {"password": PASSWORD, "totp": pyotp.TOTP(secret).now()}
        ).status_code
        == 204
    )


# --- password reset --------------------------------------------------------------------------


@pytest.mark.django_db
def test_password_reset_flow(client: Client, user: User) -> None:
    assert (
        post(client, "/password/reset-request", {"email": "nobody@example.com"}).status_code == 204
    )
    assert len(mail.outbox) == 0  # no enumeration, no mail
    assert post(client, "/password/reset-request", {"email": "JAN@example.com"}).status_code == 204
    assert len(mail.outbox) == 1
    match = re.search(r"/reset\?token=([\w-]+)", body_of(0))
    assert match is not None
    token = match.group(1)
    assert "localhost:8080/reset?token=" in body_of(0)

    other = Client()
    assert login(other, user.email).status_code == 200
    assert UserSession.objects.filter(user=user).count() == 1

    weak = post(client, "/password/reset", {"token": token, "password": "short"})
    assert weak.status_code == 400 and "password" in weak.json()["error"]["fields"]
    assert (
        post(client, "/password/reset", {"token": token, "password": NEW_PASSWORD}).status_code
        == 204
    )
    assert login(Client(), user.email, NEW_PASSWORD).status_code == 200
    assert other.get(f"{AUTH}/me").status_code in (401, 403)  # every session invalidated
    again = post(client, "/password/reset", {"token": token, "password": NEW_PASSWORD})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"


@pytest.mark.django_db
def test_password_reset_token_expires(client: Client, user: User) -> None:
    post(client, "/password/reset-request", {"email": user.email})
    PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    match = re.search(r"token=([\w-]+)", body_of(0))
    assert match is not None
    token = match.group(1)
    assert (
        post(client, "/password/reset", {"token": token, "password": NEW_PASSWORD}).status_code
        == 400
    )


@pytest.mark.django_db
def test_password_reset_request_is_throttled(client: Client, user: User) -> None:
    for _ in range(3):
        assert post(client, "/password/reset-request", {"email": user.email}).status_code == 204
    assert post(client, "/password/reset-request", {"email": user.email}).status_code == 429


# --- invitations -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_invitation_accept_creates_user_and_logs_in(client: Client, tenant: Tenant) -> None:
    from apps.accounts.services import issue_invitation

    invitation = issue_invitation(
        email="Nowa@Example.com", role=Role.TENANT_USER, tenant=tenant, created_by=None
    )
    assert len(mail.outbox) == 1 and "Klient A" in body_of(0)
    match = re.search(r"/invite/([\w-]+)", body_of(0))
    assert match is not None
    token = match.group(1)

    weak = post(client, "/invitations/accept", {"token": token, "password": "short"})
    assert weak.status_code == 400
    ok = post(client, "/invitations/accept", {"token": token, "password": NEW_PASSWORD})
    assert ok.status_code == 200, ok.content
    assert ok.json()["user"]["email"] == "nowa@example.com"
    assert ok.json()["user"]["tenant"]["id"] == str(tenant.id)
    assert client.get(f"{AUTH}/me").status_code == 200
    invitation.refresh_from_db()
    assert invitation.accepted_at is not None

    again = post(Client(), "/invitations/accept", {"token": token, "password": NEW_PASSWORD})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"


@pytest.mark.django_db
def test_invitation_expired_or_unknown(client: Client, tenant: Tenant) -> None:
    invitation, token = Invitation.issue(
        email="x@example.com", role=Role.TENANT_USER, tenant=tenant, created_by=None
    )
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])
    assert (
        post(client, "/invitations/accept", {"token": token, "password": NEW_PASSWORD}).status_code
        == 400
    )
    assert (
        post(client, "/invitations/accept", {"token": "nope", "password": NEW_PASSWORD}).status_code
        == 400
    )
