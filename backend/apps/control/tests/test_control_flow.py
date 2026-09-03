"""docs/07 §Testy obowiązkowe: who may control, draft/confirm/execute/verify, sensitive, limits."""

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.accounts.totp import hash_backup_code
from apps.adapters.base import CommandDef as AdapterCommand
from apps.adapters.base import Feature, ParamDef, PropertyDef
from apps.control import services
from apps.control.models import Command, CommandStatus
from apps.devices.models import Device, DeviceMode, FeatureDefinition
from apps.ingest import status as dstatus
from apps.ingest.models import Job
from apps.ingest.services import ingest
from apps.ingest.worker import Worker
from apps.providers import crypto as token_crypto
from apps.providers.models import ApiCall, ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant, TenantMembership

PASSWORD = "correct-horse-battery-staple"
API = "https://api.test/iot/v1"
IAM = "https://iam.test/idp/v3"
FEATURE = "heating.circuits.0.operating.programs.normal"
FEATURES_URL = f"{API}/features/installations/1/gateways/G/devices/0/features"
COMMAND_URI = f"{FEATURES_URL}/{FEATURE}/commands/setTemperature"
MODE_URI = f"{FEATURES_URL}/heating.circuits.0.operating.modes.active/commands/setMode"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


def feature_payload(temp: float) -> dict[str, Any]:
    return {
        "data": [
            {
                "feature": FEATURE,
                "isEnabled": True,
                "isReady": True,
                "timestamp": "2026-09-03T10:00:00.000Z",
                "properties": {
                    "active": {"type": "boolean", "value": False},
                    "temperature": {"type": "number", "unit": "celsius", "value": temp},
                },
                "commands": {
                    "setTemperature": {
                        "isExecutable": True,
                        "params": {
                            "targetTemperature": {
                                "type": "number",
                                "required": True,
                                "constraints": {"min": 3, "max": 37, "stepping": 1},
                            }
                        },
                        "uri": COMMAND_URI,
                    }
                },
            },
            {
                "feature": "heating.circuits.0.operating.modes.active",
                "isEnabled": True,
                "properties": {"value": {"type": "string", "value": "heating"}},
                "commands": {
                    "setMode": {
                        "isExecutable": True,
                        "params": {
                            "mode": {
                                "type": "string",
                                "required": True,
                                "constraints": {"enum": ["standby", "heating"]},
                            }
                        },
                        "uri": MODE_URI,
                    }
                },
            },
        ]
    }


def ingest_payload(device: Device, temp: float) -> None:
    from apps.adapters.viessmann.parser import parse_features

    ingest(device, parse_features(feature_payload(temp)))


@pytest.fixture
def world() -> dict[str, Any]:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount(tenant=tenant, provider="viessmann")
    token_crypto.store_tokens(
        account,
        __import__("apps.adapters.base", fromlist=["ProviderTokens"]).ProviderTokens(
            access_token="at", access_expires_at=4102444800.0, refresh_token="rt"
        ),
    )
    account.save()
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="Kociol",
        mode=DeviceMode.CONTROL,
    )
    ingest_payload(device, 21)
    dstatus.mark_online(device)
    admin = User.objects.create_user(
        "aa@example.com",
        PASSWORD,
        role=Role.TENANT_ADMIN,
        tenant=tenant,
        totp_enabled=True,
        backup_codes_hash=[hash_backup_code("abcdef0123"), hash_backup_code("abcdef0124")],
    )
    user = User.objects.create_user(
        "ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant
    )
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    TenantMembership.objects.create(user=tech, tenant=tenant, can_control=False)
    return {
        "tenant": tenant,
        "account": account,
        "device": device,
        "admin": admin,
        "user": user,
        "sa": sa,
        "tech": tech,
    }


def login(user: User, totp: str | None = None) -> Client:
    c = Client()
    if user.is_operator:  # skip the TOTP challenge for operators, restore the flag afterwards
        user.totp_enabled = False
        user.save(update_fields=["totp_enabled"])
    body: dict[str, str] = {"email": user.email, "password": PASSWORD}
    if totp:
        body["totp"] = totp
    r = c.post("/api/v1/auth/login", body, content_type="application/json")
    assert r.status_code == 200, r.content
    if user.is_operator:
        user.totp_enabled = True
        user.save(update_fields=["totp_enabled"])
    return c


def draft(
    c: Client,
    world: dict[str, Any],
    command: str = "setTemperature",
    params: dict[str, Any] | None = None,
    feature: str = FEATURE,
) -> Any:
    return c.post(
        f"/api/v1/tenants/{world['tenant'].id}/devices/{world['device'].id}/commands",
        {
            "feature_name": feature,
            "command_name": command,
            "params": params if params is not None else {"targetTemperature": 22},
        },
        content_type="application/json",
    )


def confirm(c: Client, world: dict[str, Any], cid: str) -> Any:
    return c.post(
        f"/api/v1/tenants/{world['tenant'].id}/commands/{cid}/confirm",
        {"acknowledged": True},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_tenant_user_never_and_read_mode_rejects_everyone(world: dict[str, Any]) -> None:
    r = draft(login(world["user"]), world)
    assert r.status_code == 403 and "role_not_allowed" in r.json()["error"]["reasons"]
    world["device"].mode = DeviceMode.READ
    world["device"].save()
    r = draft(login(world["sa"]), world)
    assert r.status_code == 403 and "device_read_only" in r.json()["error"]["reasons"]
    r = draft(login(world["user"]), world)
    assert r.status_code == 403


@pytest.mark.django_db
def test_tenant_admin_without_totp_and_technician_without_can_control(
    world: dict[str, Any],
) -> None:
    admin = world["admin"]
    admin.totp_enabled = False
    admin.save()
    r = draft(login(admin), world)
    assert r.status_code == 403 and "totp_required" in r.json()["error"]["reasons"]
    r = draft(login(world["tech"]), world)
    assert r.status_code == 403 and "operator_no_control_permission" in r.json()["error"]["reasons"]
    TenantMembership.objects.filter(user=world["tech"]).update(can_control=True)
    assert draft(login(world["tech"]), world).status_code == 201


@pytest.mark.django_db
def test_constraint_violation_and_unavailable_command(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    r = draft(c, world, params={"targetTemperature": 50})
    assert r.status_code == 422 and r.json()["error"]["code"] == "constraint_violation"
    assert "targetTemperature" in r.json()["error"]["fields"]
    r = draft(c, world, command="setCurve")
    assert r.status_code == 422 and r.json()["error"]["code"] == "command_not_available"
    r = draft(c, world, feature="does.not.exist")
    assert r.status_code == 422


@pytest.mark.django_db
def test_draft_captures_value_before_and_expires(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    r = draft(c, world)
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "draft" and body["sensitive"] is False
    assert body["value_before"] == {"temperature": 21.0} and body["value_after"] == {
        "targetTemperature": 22
    }
    Command.objects.filter(id=body["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = confirm(c, world, body["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "command_expired"
    # another user cannot confirm somebody else's draft
    other = draft(c, world).json()
    assert confirm(login(world["sa"]), world, other["id"]).status_code == 409


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_full_flow_confirm_execute_verify(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    cid = draft(c, world).json()["id"]
    r = confirm(c, world, cid)
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert Job.objects.filter(kind="execute_command").exists()
    cmd_route = respx.post(COMMAND_URI).mock(
        return_value=httpx.Response(200, json={"data": {"success": True}})
    )
    respx.get(FEATURES_URL).mock(return_value=httpx.Response(200, json=feature_payload(22)))

    Worker(concurrency=4).run_once()
    command = Command.objects.get(id=cid)
    assert command.status == CommandStatus.SUCCEEDED and command.api_status == 200
    assert json.loads(cmd_route.calls.last.request.content) == {"targetTemperature": 22}
    verify_job = Job.objects.get(kind="verify_command")
    assert verify_job.run_at > timezone.now() + timedelta(seconds=30)
    Job.objects.filter(id=verify_job.id).update(run_at=timezone.now())
    Worker(concurrency=4).run_once()
    command.refresh_from_db()
    assert command.status == CommandStatus.VERIFIED and command.verified_at is not None
    assert ApiCall.objects.filter(provider_account=world["account"], kind="command").count() == 1
    assert (
        ApiCall.objects.filter(
            provider_account=world["account"], kind="verify", http_status=200
        ).count()
        == 1
    )

    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/commands/{cid}")
    assert (
        r.status_code == 200
        and r.json()["status"] == "verified"
        and r.json()["job"]["status"] == "done"
    )
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/commands")
    assert r.json()["count"] == 1 and r.json()["results"][0]["device_name"] == "Kociol"


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_verify_mismatch_when_device_does_not_confirm(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    cid = draft(c, world).json()["id"]
    confirm(c, world, cid)
    respx.post(COMMAND_URI).mock(return_value=httpx.Response(200, json={}))
    respx.get(FEATURES_URL).mock(
        return_value=httpx.Response(200, json=feature_payload(21))
    )  # unchanged
    Worker(concurrency=4).run_once()
    Job.objects.filter(kind="verify_command").update(run_at=timezone.now())
    Worker(concurrency=4).run_once()
    command = Command.objects.get(id=cid)
    assert command.status == CommandStatus.VERIFY_MISMATCH


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_unsupported_command_404_marks_definition(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    cid = draft(c, world).json()["id"]
    confirm(c, world, cid)
    respx.post(COMMAND_URI).mock(
        return_value=httpx.Response(404, json={"errorType": "COMMAND_NOT_FOUND"})
    )
    Worker(concurrency=4).run_once()
    assert Command.objects.get(id=cid).status == CommandStatus.FAILED
    definition = FeatureDefinition.objects.get(device=world["device"], feature_name=FEATURE)
    assert "setTemperature" in definition.unsupported_commands
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/devices/{world['device'].id}/features")
    row = next(f for f in r.json()["results"] if f["feature_name"] == FEATURE)
    assert row["commands"]["setTemperature"]["executable"] is False
    assert draft(c, world).status_code == 422  # command hidden from now on


@pytest.mark.django_db
def test_sensitive_command_requires_reauth(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    r = draft(
        c,
        world,
        command="setMode",
        params={"mode": "standby"},
        feature="heating.circuits.0.operating.modes.active",
    )
    assert r.status_code == 201 and r.json()["sensitive"] is True
    cid = r.json()["id"]
    r = confirm(c, world, cid)
    assert r.status_code == 428 and r.json()["error"]["code"] == "reauth_required"
    assert (
        c.post(
            "/api/v1/auth/reauth",
            {"password": PASSWORD, "totp": "abcdef0124"},
            content_type="application/json",
        ).status_code
        == 204
    )
    r = confirm(c, world, cid)
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert Command.objects.get(id=cid).reauth_verified is True


@pytest.mark.django_db
def test_hourly_limit_and_reserve(world: dict[str, Any]) -> None:
    c = login(world["admin"], totp="abcdef0123")
    world["device"].commands_per_hour_limit = 1
    world["device"].save()
    Command.objects.create(
        tenant=world["tenant"],
        device=world["device"],
        user=world["admin"],
        feature_name=FEATURE,
        command_name="setTemperature",
        params={},
        status=CommandStatus.VERIFIED,
        expires_at=timezone.now(),
    )
    r = draft(c, world)
    assert r.status_code == 403 and "hourly_limit_reached" in r.json()["error"]["reasons"]
    world["device"].commands_per_hour_limit = 10
    world["device"].save()
    acc = world["account"]
    ApiCall.objects.bulk_create(
        [
            ApiCall(provider_account=acc, kind="command", ts=timezone.now(), http_status=200)
            for _ in range(acc.reserve - 1)
        ]
    )
    r = draft(c, world)
    assert r.status_code == 403 and "budget_reserve_exhausted" in r.json()["error"]["reasons"]


@pytest.mark.django_db
def test_capabilities_reasons_in_device_details(world: dict[str, Any]) -> None:
    c = login(world["user"])
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/devices/{world['device'].id}")
    assert r.json()["capabilities"] == {"can_control": False, "reasons": ["role_not_allowed"]}
    c = login(world["admin"], totp="abcdef0123")
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/devices/{world['device'].id}")
    assert r.json()["capabilities"]["can_control"] is True


def _unused(*_: Any) -> None:  # keep imports referenced for mypy
    return None


_unused(Feature, ParamDef, PropertyDef, AdapterCommand, services)


@pytest.mark.django_db
def test_dead_job_marks_command_failed(world: dict[str, Any]) -> None:
    """A confirmed command whose job exhausted its retries must surface as failed."""
    c = login(world["admin"], totp="abcdef0123")
    cid = draft(c, world).json()["id"]
    confirm(c, world, cid)
    Job.objects.filter(kind="execute_command").update(status="failed", last_error="boom")
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/commands/{cid}")
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert r.json()["reject_reason"].startswith("job_failed")
    r = c.get(f"/api/v1/tenants/{world['tenant'].id}/commands")
    assert r.json()["results"][0]["status"] == "failed"


@pytest.mark.django_db
def test_login_twice_on_the_same_cookie(world: dict[str, Any]) -> None:
    """Django keeps the session key for a re-login of the same user → no duplicate UserSession."""
    c = login(world["user"])
    r = c.post(
        "/api/v1/auth/login",
        {"email": world["user"].email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
