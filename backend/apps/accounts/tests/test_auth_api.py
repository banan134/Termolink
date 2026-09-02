"""Auth API tests (docs/12 §Auth). Requests go through the full middleware stack."""

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.accounts.api import LoginThrottle
from apps.accounts.models import LoginAttempt, Role, User, UserSession
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "another-long-passphrase-42"
LOGIN = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _isolated_throttle_cache() -> None:
    cache.clear()


@pytest.fixture
def no_login_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    # DRF snapshots DEFAULT_THROTTLE_RATES at class-definition time, so patch the class.
    monkeypatch.setattr(LoginThrottle, "THROTTLE_RATES", {"login": "1000/min"})


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(name="Klient A")


@pytest.fixture
def user(tenant: Tenant) -> User:
    return User.objects.create_user(
        "jan@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )


def do_login(client: Client, email: str = "jan@example.com", password: str = PASSWORD) -> Any:
    return client.post(
        LOGIN, {"email": email, "password": password}, content_type="application/json"
    )


@pytest.mark.django_db
def test_login_sets_session_and_returns_me(client: Client, user: User, tenant: Tenant) -> None:
    response = do_login(client)
    assert response.status_code == 200, response.content
    body = response.json()["user"]
    assert body["email"] == "jan@example.com"
    assert body["role"] == "tenant_admin"
    assert body["tenant"] == {"id": str(tenant.id), "name": "Klient A"}
    assert body["allowed_tenants"] == []
    assert UserSession.objects.filter(user=user).count() == 1
    user.refresh_from_db()
    assert user.last_login is not None


@pytest.mark.django_db
def test_login_wrong_password_401_with_error_format(client: Client, user: User) -> None:
    response = do_login(client, password="nope")
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_credentials",
            "message": "Nieprawidłowy e-mail lub hasło.",
            "fields": {},
        }
    }
    assert LoginAttempt.objects.filter(email_lower="jan@example.com", success=False).count() == 1


@pytest.mark.django_db
def test_lockout_after_ten_failures_then_escalating_delay(
    client: Client, user: User, no_login_throttle: None
) -> None:
    for _ in range(10):
        assert do_login(client, password="nope").status_code == 401
    response = do_login(client)  # even the right password is locked out now
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "login_locked"
    assert 0 < body["retry_after_s"] <= 61

    # first failure older than the delay → unlocked; success clears the counter
    LoginAttempt.objects.update(ts=timezone.now() - timedelta(minutes=2))
    assert do_login(client).status_code == 200
    assert not LoginAttempt.objects.filter(success=False).exists()


@pytest.mark.django_db
def test_lockout_is_also_per_ip(client: Client, user: User, no_login_throttle: None) -> None:
    for i in range(10):
        do_login(client, email=f"other{i}@example.com", password="nope")
    assert do_login(client).status_code == 429


@pytest.mark.django_db
def test_login_is_throttled_per_ip(client: Client, user: User) -> None:
    for _ in range(5):
        do_login(client, password="nope")
    response = do_login(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "throttled"


@pytest.mark.django_db
def test_login_requires_totp_when_enabled(client: Client, user: User) -> None:
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    response = do_login(client)
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "totp_required"


@pytest.mark.django_db
def test_me_requires_auth_and_reports_operator_tenants(client: Client, tenant: Tenant) -> None:
    assert client.get("/api/v1/auth/me").status_code in (401, 403)
    User.objects.create_superuser("admin@example.com", PASSWORD)
    assert do_login(client, email="admin@example.com").status_code == 200
    body = client.get("/api/v1/auth/me").json()
    assert body["role"] == "superadmin"
    assert body["tenant"] is None
    assert body["allowed_tenants"] == [str(tenant.id)]


@pytest.mark.django_db
def test_patch_me_theme(client: Client, user: User) -> None:
    do_login(client)
    response = client.patch(
        "/api/v1/auth/me", {"ui_theme": "dark"}, content_type="application/json"
    )
    assert response.status_code == 200 and response.json()["ui_theme"] == "dark"
    bad = client.patch("/api/v1/auth/me", {"ui_theme": "neon"}, content_type="application/json")
    assert bad.status_code == 400
    assert "ui_theme" in bad.json()["error"]["fields"]


@pytest.mark.django_db
def test_password_change_invalidates_other_sessions(user: User) -> None:
    c1, c2 = Client(), Client()
    assert do_login(c1).status_code == 200
    assert do_login(c2).status_code == 200
    assert UserSession.objects.filter(user=user).count() == 2

    response = c1.post(
        "/api/v1/auth/password/change",
        {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 204, response.content
    assert c1.get("/api/v1/auth/me").status_code == 200  # current session survives
    assert c2.get("/api/v1/auth/me").status_code in (401, 403)  # other one is gone
    assert UserSession.objects.filter(user=user).count() == 1
    assert Session.objects.count() == 1
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


@pytest.mark.django_db
def test_password_change_rejects_wrong_old_and_weak_new(client: Client, user: User) -> None:
    do_login(client)
    wrong = client.post(
        "/api/v1/auth/password/change",
        {"old_password": "nope", "new_password": NEW_PASSWORD},
        content_type="application/json",
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invalid_password"
    weak = client.post(
        "/api/v1/auth/password/change",
        {"old_password": PASSWORD, "new_password": "short"},
        content_type="application/json",
    )
    assert weak.status_code == 400 and "new_password" in weak.json()["error"]["fields"]


@pytest.mark.django_db
def test_sessions_list_and_remote_logout(user: User) -> None:
    c1, c2 = Client(), Client()
    do_login(c1)
    do_login(c2)
    rows = c1.get("/api/v1/auth/sessions").json()["results"]
    assert len(rows) == 2 and sum(r["current"] for r in rows) == 1
    other = next(r for r in rows if not r["current"])
    assert c1.delete(f"/api/v1/auth/sessions/{other['id']}").status_code == 204
    assert c2.get("/api/v1/auth/me").status_code in (401, 403)
    assert (
        c1.delete("/api/v1/auth/sessions/00000000-0000-0000-0000-000000000000").status_code == 404
    )
    # deleting the current session logs out
    current = next(r for r in rows if r["current"])
    assert c1.delete(f"/api/v1/auth/sessions/{current['id']}").status_code == 204
    assert c1.get("/api/v1/auth/me").status_code in (401, 403)


@pytest.mark.django_db
def test_logout(client: Client, user: User) -> None:
    do_login(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code in (401, 403)
    assert UserSession.objects.count() == 0


@pytest.mark.django_db
def test_session_absolute_max_age(client: Client, user: User) -> None:
    do_login(client)
    session = client.session
    session["login_at"] = (timezone.now() - timedelta(days=8)).isoformat()
    session.save()
    assert client.get("/api/v1/auth/me").status_code in (401, 403)


@pytest.mark.django_db
def test_sessions_are_isolated_between_users(client: Client, user: User, tenant: Tenant) -> None:
    other = User.objects.create_user(
        "ola@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant
    )
    c2 = Client()
    do_login(c2, email="ola@example.com")
    do_login(client)
    ids = {r["id"] for r in client.get("/api/v1/auth/sessions").json()["results"]}
    assert ids == {str(UserSession.objects.get(user=user).id)}
    foreign = UserSession.objects.get(user=other)
    assert client.delete(f"/api/v1/auth/sessions/{foreign.id}").status_code == 404
