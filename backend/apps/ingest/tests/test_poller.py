"""Scheduler + poller against a mocked Viessmann API (respx) — docs/06."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from django.test import override_settings
from django.utils import timezone

from apps.adapters.base import ProviderTokens
from apps.devices.models import Device, DeviceStatus, FeatureLatest
from apps.ingest import poller
from apps.ingest.models import Job
from apps.ingest.worker import Worker
from apps.providers import crypto as token_crypto
from apps.providers.models import ApiCall, ProviderAccount
from apps.tenants.models import Tenant

API = "https://api.test/iot/v1"
IAM = "https://iam.test/idp/v3"


def make_account(tenant: Tenant, **kw: Any) -> ProviderAccount:
    account = ProviderAccount(tenant=tenant, provider="viessmann", **kw)
    token_crypto.store_tokens(
        account,
        ProviderTokens(access_token="at", access_expires_at=4102444800.0, refresh_token="rt"),
    )
    account.save()
    return account


def make_device(account: ProviderAccount, dev_id: str = "0", **kw: Any) -> Device:
    return Device.objects.create(
        tenant=account.tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": dev_id},
        display_name=f"dev-{dev_id}",
        model="Vitocal",
        **kw,
    )


FEATURES = {
    "data": [
        {
            "feature": "heating.sensors.temperature.outside",
            "isEnabled": True,
            "properties": {"value": {"type": "number", "unit": "celsius", "value": 12.5}},
            "commands": {},
            "timestamp": "2026-09-03T10:00:00.000Z",
        }
    ]
}


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_scheduler_enqueues_and_poller_ingests() -> None:
    tenant = Tenant.objects.create(name="A")
    account = make_account(tenant)
    device = make_device(account)
    respx.get(f"{API}/features/installations/1/gateways/G/devices/0/features").mock(
        return_value=httpx.Response(200, json=FEATURES)
    )

    assert poller.schedule_polls() == 1
    assert poller.schedule_polls() == 0  # already pending
    job = Job.objects.get(kind="poll")
    assert job.payload == {"device_id": str(device.id)} and job.provider_account_id == account.id
    device.refresh_from_db()
    assert device.next_poll_at > timezone.now() + timedelta(seconds=60)

    Worker(concurrency=2).run_once()
    job.refresh_from_db()
    assert job.status == "done", job.last_error
    assert job.result is not None
    assert job.result["status"] == "online" and job.result["features"] == 1
    device.refresh_from_db()
    assert device.status == DeviceStatus.ONLINE and device.last_seen_at is not None
    latest = FeatureLatest.objects.get(device=device)
    assert latest.value_num == 12.5 and latest.unit == "celsius"
    call = ApiCall.objects.get(provider_account=account)
    assert call.kind == "poll" and call.http_status == 200 and call.device_id == device.id


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_gateway_offline_marks_device_offline_not_job_failure() -> None:
    tenant = Tenant.objects.create(name="A")
    account = make_account(tenant)
    device = make_device(account)
    respx.get(f"{API}/features/installations/1/gateways/G/devices/0/features").mock(
        return_value=httpx.Response(
            400,
            json={
                "errorType": "DEVICE_COMMUNICATION_ERROR",
                "extendedPayload": {"reason": "GATEWAY_OFFLINE"},
            },
        )
    )
    result = poller.poll_device(device)
    assert result == {"status": "offline"}
    device.refresh_from_db()
    assert device.status == DeviceStatus.OFFLINE and "GATEWAY_OFFLINE" in (
        device.status_detail or ""
    )


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_rate_limit_pauses_account_and_scheduler_skips_it() -> None:
    tenant = Tenant.objects.create(name="A")
    account = make_account(tenant)
    device = make_device(account)
    respx.get(f"{API}/features/installations/1/gateways/G/devices/0/features").mock(
        return_value=httpx.Response(
            429, json={"message": "rate limit"}, headers={"Retry-After": "120"}
        )
    )
    assert poller.poll_device(device)["status"] == "rate_limited"
    account.refresh_from_db()
    assert account.status == "rate_limited" and account.status_until is not None
    device.refresh_from_db()
    assert device.status == DeviceStatus.RATE_LIMITED
    assert poller.schedule_polls() == 0
    account.status_until = timezone.now() - timedelta(seconds=1)
    account.save()
    device.next_poll_at = timezone.now() - timedelta(seconds=1)
    device.save()
    assert poller.schedule_polls() == 1  # window over → active again


@pytest.mark.django_db
@override_settings(VIESSMANN_API_BASE=API, VIESSMANN_IAM_BASE=IAM)
@respx.mock
def test_auth_error_marks_reauth_required() -> None:
    tenant = Tenant.objects.create(name="A")
    account = make_account(tenant)
    device = make_device(account)
    respx.get(f"{API}/features/installations/1/gateways/G/devices/0/features").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    assert poller.poll_device(device)["status"] == "reauth_required"
    account.refresh_from_db()
    assert account.status == "reauth_required"


@pytest.mark.django_db
def test_scheduler_respects_poll_budget_and_spreads_devices() -> None:
    tenant = Tenant.objects.create(name="A")
    account = make_account(tenant, budget_limit=100, budget_reserve_pct=10)
    for i in range(3):
        make_device(account, dev_id=str(i))
    ApiCall.objects.bulk_create(
        [
            ApiCall(provider_account=account, kind="poll", ts=timezone.now(), http_status=200)
            for _ in range(89)
        ]
    )
    assert poller.schedule_polls() == 1  # only one poll slot left in the budget
    assert Job.objects.filter(kind="poll").count() == 1
