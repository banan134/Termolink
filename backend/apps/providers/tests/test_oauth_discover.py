"""OAuth connect flow and discover against a mocked Viessmann (respx) — docs/02 §A."""

import re
from typing import Any

import httpx
import pytest
import respx
from django.test import Client, override_settings

from apps.accounts.models import Role, User
from apps.devices.models import DiscoveredDevice
from apps.ingest.models import Job
from apps.ingest.worker import Worker
from apps.providers import crypto as token_crypto
from apps.providers.models import ApiCall, OAuthState, ProviderAccount
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
IAM = "https://iam.test/idp/v3"
API = "https://api.test/iot/v1"


@pytest.fixture
def operator() -> User:
    user = User.objects.create_superuser("sa@example.com", PASSWORD)
    return user


def login(user: User) -> Client:
    client = Client()
    r = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200
    user.totp_enabled = True  # skip the operator 2FA gate in API tests
    user.save(update_fields=["totp_enabled"])
    return client


INSTALLATIONS: dict[str, Any] = {
    "data": [
        {
            "id": 555,
            "gateways": [
                {
                    "serial": "ANON000100000000",
                    "devices": [
                        {
                            "id": "0",
                            "modelId": "Vitocal_250A",
                            "deviceType": "heating",
                            "status": "Online",
                        },
                        {"id": "gateway", "modelId": "Vitoconnect_OPTO2"},
                    ],
                }
            ],
        }
    ]
}


@pytest.mark.django_db
@override_settings(VIESSMANN_CLIENT_ID="cid", VIESSMANN_IAM_BASE=IAM, VIESSMANN_API_BASE=API)
@respx.mock
def test_full_connect_and_discover_flow(operator: User) -> None:
    tenant = Tenant.objects.create(name="A")
    client = login(operator)

    # 1. operator starts authorization → redirect URL to the IdP
    r = client.post(
        f"/api/v1/tenants/{tenant.id}/provider-accounts/viessmann/authorize",
        {"label": "Dom"},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    url = r.json()["redirect_url"]
    assert url.startswith(f"{IAM}/authorize?") and "code_challenge=" in url
    state = re.search(r"state=([^&]+)", url).group(1)  # type: ignore[union-attr]
    assert OAuthState.objects.filter(state=state, tenant=tenant).exists()

    # 2. IdP redirects back with a code → token exchange → account + discover job
    respx.post(f"{IAM}/token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "sub": "user-1"},
        )
    )
    r = Client().get(f"/oauth/viessmann/callback?code=abc&state={state}")
    assert r.status_code == 302
    assert f"/admin/tenants/{tenant.id}?provider=viessmann&connected=" in r["Location"]
    account = ProviderAccount.objects.get(tenant=tenant)
    assert (
        account.status == "active"
        and account.label == "Dom"
        and account.external_user_id == "user-1"
    )
    assert token_crypto.load_tokens(account).refresh_token == "rt"
    assert not OAuthState.objects.filter(state=state).exists()
    job = Job.objects.get(kind="discover")
    assert job.payload == {"account_id": str(account.id)} and job.tenant == tenant

    # 3. worker runs discover → discovered_devices; one API call from the reserve
    respx.get(f"{API}/equipment/installations?includeGateways=true").mock(
        return_value=httpx.Response(200, json=INSTALLATIONS)
    )
    Worker(concurrency=2).run_once()
    job.refresh_from_db()
    assert job.status == "done" and job.result == {"devices": 2}, job.last_error
    assert DiscoveredDevice.objects.filter(provider_account=account).count() == 2
    assert (
        ApiCall.objects.filter(provider_account=account, kind="discover", http_status=200).count()
        == 1
    )

    # 4. operator sees the tree with already_added flags and the account budget
    r = client.get(f"/api/v1/tenants/{tenant.id}/provider-accounts/{account.id}/discovered")
    assert r.status_code == 200
    devices = r.json()["installations"][0]["gateways"][0]["devices"]
    assert [d["device_id"] for d in devices] == ["0", "gateway"]
    assert devices[0]["already_added"] is False and devices[1]["is_gateway"] is True
    r = client.get(f"/api/v1/tenants/{tenant.id}/provider-accounts")
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert (
        row["budget"]["used"] == 1 and row["budget"]["limit"] == 1450 and row["status"] == "active"
    )

    # 5. "discover again" → 202 with a job id
    r = client.post(f"/api/v1/tenants/{tenant.id}/provider-accounts/{account.id}/discover")
    assert r.status_code == 202 and "job_id" in r.json()

    # 6. disconnect → disabled, tokens wiped
    r = client.delete(f"/api/v1/tenants/{tenant.id}/provider-accounts/{account.id}")
    assert r.status_code == 204
    account.refresh_from_db()
    assert account.status == "disabled" and bytes(account.refresh_token_enc) == b""


@pytest.mark.django_db
@override_settings(VIESSMANN_CLIENT_ID="cid", VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_callback_errors(operator: User) -> None:
    tenant = Tenant.objects.create(name="A")
    client = login(operator)
    r = Client().get("/oauth/viessmann/callback?code=x&state=bogus")
    assert r.status_code == 302 and "error=invalid_state" in r["Location"]

    url = client.post(
        f"/api/v1/tenants/{tenant.id}/provider-accounts/viessmann/authorize",
        {},
        content_type="application/json",
    ).json()["redirect_url"]
    state = re.search(r"state=([^&]+)", url).group(1)  # type: ignore[union-attr]
    r = Client().get(f"/oauth/viessmann/callback?error=access_denied&state={state}")
    assert "error=access_denied" in r["Location"] and not ProviderAccount.objects.exists()

    url = client.post(
        f"/api/v1/tenants/{tenant.id}/provider-accounts/viessmann/authorize",
        {},
        content_type="application/json",
    ).json()["redirect_url"]
    state = re.search(r"state=([^&]+)", url).group(1)  # type: ignore[union-attr]
    respx.post(f"{IAM}/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    r = Client().get(f"/oauth/viessmann/callback?code=bad&state={state}")
    assert "error=token_exchange_failed" in r["Location"]


@pytest.mark.django_db
@override_settings(VIESSMANN_CLIENT_ID="")
def test_authorize_requires_client_id(operator: User) -> None:
    tenant = Tenant.objects.create(name="A")
    client = login(operator)
    r = client.post(
        f"/api/v1/tenants/{tenant.id}/provider-accounts/viessmann/authorize",
        {},
        content_type="application/json",
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"


@pytest.mark.django_db
def test_tenant_user_cannot_see_provider_accounts() -> None:
    tenant = Tenant.objects.create(name="A")
    User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    client = Client()
    client.post(
        "/api/v1/auth/login",
        {"email": "u@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    assert client.get(f"/api/v1/tenants/{tenant.id}/provider-accounts").status_code == 403
