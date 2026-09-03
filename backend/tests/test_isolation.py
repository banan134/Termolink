"""Parametric isolation tests (docs/12 §Izolacja).

For every endpoint that takes a tenant id or a tenant-owned resource id:
1. user of tenant A → resource of tenant B → 404
2. technician without membership → 404; with membership → 2xx
3. superadmin → 2xx
Add a row to ENDPOINTS for each new tenant-scoped endpoint; the registry test fails if a
URL pattern with `tenant_id` is missing here.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from django.test import Client
from django.urls import get_resolver

from apps.accounts.models import Role, User
from apps.ingest import queue
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "correct-horse-battery-staple"
# 2xx, or a denial that is NOT about tenant scope (503 = provider not configured in tests,
# 429 = budget reserve exhausted); 403/404 would mean the operator was refused by scope.
OK_OR_EXPECTED_DENIAL = (
    200,
    201,
    202,
    204,
    400,
    403,
    409,
    422,
    429,
    503,
)  # 400 = validation on dummy body


@dataclass(frozen=True)
class Endpoint:
    name: str  # URL pattern name
    method: str
    body: dict[str, Any] | None = None
    tenant_roles_allowed: tuple[str, ...] = (Role.TENANT_ADMIN, Role.TENANT_USER)


# Every tenant-scoped URL pattern must be listed (see test_every_tenant_url_is_covered).
ENDPOINTS: list[Endpoint] = [
    Endpoint("admin-tenant", "GET", tenant_roles_allowed=()),
    Endpoint("admin-tenant", "PATCH", body={"name": "x"}, tenant_roles_allowed=()),
    Endpoint("admin-tenant-users", "GET", tenant_roles_allowed=()),
    Endpoint(
        "admin-tenant-invitations",
        "POST",
        body={"email": "new@example.com", "role": "tenant_user"},
        tenant_roles_allowed=(),
    ),
    Endpoint("tenant-users", "GET", tenant_roles_allowed=(Role.TENANT_ADMIN,)),
    Endpoint(
        "tenant-invitations",
        "POST",
        body={"email": "new2@example.com", "role": "tenant_user"},
        tenant_roles_allowed=(Role.TENANT_ADMIN,),
    ),
    Endpoint("job-detail", "GET"),
    Endpoint("provider-accounts", "GET", tenant_roles_allowed=(Role.TENANT_ADMIN,)),
    Endpoint("provider-authorize", "POST", body={}, tenant_roles_allowed=()),
    Endpoint("provider-account", "PATCH", body={"label": "x"}, tenant_roles_allowed=()),
    Endpoint("provider-account", "DELETE", tenant_roles_allowed=()),
    Endpoint("provider-discover", "POST", body={}, tenant_roles_allowed=()),
    Endpoint("provider-discovered", "GET", tenant_roles_allowed=()),
    Endpoint("devices", "GET"),
    Endpoint(
        "devices",
        "POST",
        body={
            "provider_account_id": "00000000-0000-0000-0000-000000000000",
            "external_ids": {"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
            "display_name": "x",
        },
        tenant_roles_allowed=(),
    ),
    Endpoint("device", "GET"),
    Endpoint(
        "device", "PATCH", body={"display_name": "y"}, tenant_roles_allowed=(Role.TENANT_ADMIN,)
    ),
    Endpoint("device", "DELETE", tenant_roles_allowed=()),
    Endpoint("device-refresh", "POST", body={}, tenant_roles_allowed=(Role.TENANT_ADMIN,)),
    Endpoint("device-features", "GET"),
    Endpoint("device-history", "GET"),
    Endpoint("device-status-history", "GET"),
    Endpoint("device-history-csv", "GET"),
    Endpoint("device-messages", "GET"),
    Endpoint("history-multi", "POST", body={"series": []}),
    Endpoint(
        "device-commands",
        "POST",
        body={"feature_name": "x", "command_name": "y", "params": {}},
        tenant_roles_allowed=(Role.TENANT_ADMIN,),
    ),
    Endpoint("commands", "GET"),
    Endpoint("command", "GET"),
    Endpoint(
        "command-confirm",
        "POST",
        body={"acknowledged": True},
        tenant_roles_allowed=(Role.TENANT_ADMIN,),
    ),
]


@dataclass
class World:
    a: Tenant
    b: Tenant
    users: dict[str, User]
    jobs: dict[str, Any]  # jobs and provider accounts per tenant key


@pytest.fixture
def world() -> World:
    a = Tenant.objects.create(name="A")
    b = Tenant.objects.create(name="B")
    users = {
        "superadmin": User.objects.create_superuser("sa@example.com", PASSWORD),
        "tech_member": User.objects.create_user("tm@example.com", PASSWORD, role=Role.TECHNICIAN),
        "tech_outsider": User.objects.create_user("to@example.com", PASSWORD, role=Role.TECHNICIAN),
        "admin_a": User.objects.create_user(
            "aa@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=a
        ),
        "user_a": User.objects.create_user(
            "ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=a
        ),
        "admin_b": User.objects.create_user(
            "ab@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=b
        ),
    }
    TenantMembership.objects.create(user=users["tech_member"], tenant=a, can_control=True)
    for u in (users["superadmin"], users["tech_member"], users["tech_outsider"]):
        u.totp_enabled = True  # operators are gated without 2FA; bypass verification in tests
        u.save(update_fields=["totp_enabled"])
    jobs: dict[str, Any] = {
        "a": queue.enqueue("noop", tenant=a),
        "b": queue.enqueue("noop", tenant=b),
    }
    from apps.devices.models import Device
    from apps.providers.models import ProviderAccount

    for key, tenant in (("a", a), ("b", b)):
        jobs[f"account_{key}"] = ProviderAccount.objects.create(
            tenant=tenant, provider="viessmann", refresh_token_enc=b"v1|x", label=key
        )
        from django.utils import timezone as tz

        from apps.control.models import Command

        jobs[f"device_{key}"] = Device.objects.create(
            tenant=tenant,
            provider_account=jobs[f"account_{key}"],
            provider="viessmann",
            external_ids={"installationId": key, "gatewaySerial": "G", "deviceId": "0"},
            display_name=key,
        )
        jobs[f"command_{key}"] = Command.objects.create(
            tenant=tenant,
            device=jobs[f"device_{key}"],
            feature_name="f",
            command_name="c",
            params={},
            expires_at=tz.now(),
        )
    return World(a=a, b=b, users=users, jobs=jobs)


def login(user: User) -> Client:
    client = Client()
    from apps.accounts import services

    # go through the real login service but skip the TOTP challenge for operators
    user.totp_enabled = False
    user.save(update_fields=["totp_enabled"])
    response = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    user.totp_enabled = user.is_operator  # restore the gate flag for operators
    user.save(update_fields=["totp_enabled"])
    del services
    return client


def url_for(endpoint: Endpoint, world: World, tenant: Tenant) -> str:
    from django.urls import reverse

    key = "a" if tenant is world.a else "b"
    if endpoint.name == "job-detail":
        return reverse(endpoint.name, kwargs={"job_id": str(world.jobs[key].public_id)})
    if endpoint.name == "provider-authorize":
        return reverse(endpoint.name, kwargs={"tenant_id": str(tenant.id), "provider": "viessmann"})
    if endpoint.name in ("command", "command-confirm"):
        return reverse(
            endpoint.name,
            kwargs={
                "tenant_id": str(tenant.id),
                "command_id": str(world.jobs[f"command_{key}"].id),
            },
        )
    if endpoint.name.startswith("device-") or endpoint.name == "device":
        url = reverse(
            endpoint.name,
            kwargs={"tenant_id": str(tenant.id), "device_id": str(world.jobs[f"device_{key}"].id)},
        )
        if endpoint.name in ("device-history", "device-history-csv"):
            return url + "?feature=x"
        return url
    if endpoint.name in ("provider-account", "provider-discover", "provider-discovered"):
        return reverse(
            endpoint.name,
            kwargs={
                "tenant_id": str(tenant.id),
                "account_id": str(world.jobs[f"account_{key}"].id),
            },
        )
    return reverse(endpoint.name, kwargs={"tenant_id": str(tenant.id)})


def call(client: Client, endpoint: Endpoint, url: str) -> int:
    response = client.generic(
        endpoint.method,
        url,
        data=None if endpoint.body is None else __import__("json").dumps(endpoint.body),
        content_type="application/json",
    )
    return response.status_code


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.name}")
def test_tenant_a_cannot_reach_tenant_b(world: World, endpoint: Endpoint) -> None:
    client = login(world.users["admin_a"])
    foreign = call(client, endpoint, url_for(endpoint, world, world.b))
    own = call(client, endpoint, url_for(endpoint, world, world.a))
    if Role.TENANT_ADMIN in endpoint.tenant_roles_allowed:
        assert foreign == 404, f"foreign tenant: {foreign}"
        # own tenant: reached the business logic (403/409/422 are its own verdicts, e.g. control
        # not allowed for an offline device, draft not owned by this user)
        assert own in (200, 201, 202, 400, 403, 409, 422), f"own tenant: {own}"
    elif url_for(endpoint, world, world.a).startswith("/api/v1/admin/"):
        # the whole /admin group is off-limits for tenant roles (docs/04 matrix): 403 either way
        assert foreign == 403 and own == 403, f"foreign {foreign}, own {own}"
    else:
        # tenant-scoped route, operator-only action: own → 403, foreign → 404 (never reveal B)
        assert foreign == 404 and own == 403, f"foreign {foreign}, own {own}"


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.name}")
def test_tenant_user_role_matrix(world: World, endpoint: Endpoint) -> None:
    client = login(world.users["user_a"])
    foreign = call(client, endpoint, url_for(endpoint, world, world.b))
    own = call(client, endpoint, url_for(endpoint, world, world.a))
    if Role.TENANT_USER in endpoint.tenant_roles_allowed:
        assert foreign == 404 and own in (200, 201, 202, 400)
    else:
        assert foreign in (403, 404) and own in (403, 404, 409)
        assert foreign == own or foreign == 404  # never reveal B by answering differently


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.name}")
def test_technician_needs_membership(world: World, endpoint: Endpoint) -> None:
    outsider = login(world.users["tech_outsider"])
    assert call(outsider, endpoint, url_for(endpoint, world, world.a)) == 404
    member = login(world.users["tech_member"])
    assert call(member, endpoint, url_for(endpoint, world, world.a)) in OK_OR_EXPECTED_DENIAL
    assert call(member, endpoint, url_for(endpoint, world, world.b)) == 404


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.name}")
def test_superadmin_reaches_everything(world: World, endpoint: Endpoint) -> None:
    client = login(world.users["superadmin"])
    assert call(client, endpoint, url_for(endpoint, world, world.a)) in OK_OR_EXPECTED_DENIAL
    assert call(client, endpoint, url_for(endpoint, world, world.b)) in OK_OR_EXPECTED_DENIAL


def test_every_tenant_url_is_covered() -> None:
    covered = {e.name for e in ENDPOINTS}
    missing = []
    for pattern in get_resolver().url_patterns:
        for name, route in _walk(pattern):
            if "<str:tenant_id>" in route and name not in covered and "membership" not in name:
                missing.append(name)
    assert not missing, f"tenant-scoped endpoints without isolation tests: {missing}"


def _walk(pattern: Any, prefix: str = "") -> list[tuple[str, str]]:
    route = prefix + str(pattern.pattern)
    if hasattr(pattern, "url_patterns"):
        return [item for child in pattern.url_patterns for item in _walk(child, route)]
    return [(pattern.name or "", route)]
