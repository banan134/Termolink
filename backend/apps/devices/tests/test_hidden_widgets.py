"""Hidden tiles are a per-device, tenant-wide setting editable by tenant_admin and operators."""

from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role, User
from apps.devices.models import Device
from apps.providers.models import ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


def _login(user: User) -> Client:
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return c


@pytest.mark.django_db
def test_hidden_widgets_roundtrip_and_roles() -> None:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount.objects.create(tenant=tenant, provider="viessmann")
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"deviceId": "0"},
        display_name="K",
    )
    admin = User.objects.create_user(
        "a@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    user = User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    url = f"/api/v1/tenants/{tenant.id}/devices/{device.id}"
    body: dict[str, Any] = {"hidden_widgets": ["heating.sensors.temperature.outside.value"]}
    r = _login(admin).patch(url, body, content_type="application/json")
    assert r.status_code == 200, r.content
    assert r.json()["hidden_widgets"] == body["hidden_widgets"]
    assert Device.objects.get(id=device.id).hidden_widgets == body["hidden_widgets"]
    c = _login(user)
    assert c.get(url).json()["hidden_widgets"] == body["hidden_widgets"]
    assert c.patch(url, {"hidden_widgets": []}, content_type="application/json").status_code == 403
    r = _login(admin).patch(url, {"lat": 53.1, "lon": 20.2}, content_type="application/json")
    assert r.json()["lat"] == 53.1 and r.json()["lon"] == 20.2
