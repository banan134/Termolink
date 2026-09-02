"""Budget tests (docs/12 §Budżet): windows, reserve, concurrency, auto_interval."""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.providers import budget
from apps.providers.models import ApiCall, CallKind, ProviderAccount
from apps.tenants.context import system_context
from apps.tenants.models import Tenant


def make_account(**overrides: object) -> ProviderAccount:
    tenant = Tenant.objects.create(name="A")
    fields = {
        "tenant": tenant,
        "provider": "viessmann",
        "refresh_token_enc": b"v1|x",
        "budget_limit": 100,
        "budget_window_s": 86400,
        "budget_reserve_pct": 10,
        "short_limit": 120,
        "short_window_s": 600,
    }
    fields.update(overrides)
    return ProviderAccount.objects.create(**fields)


def backfill(account: ProviderAccount, kind: str, n: int, age_s: int = 0) -> None:
    ts = timezone.now() - timedelta(seconds=age_s)
    ApiCall.objects.bulk_create(
        [ApiCall(provider_account=account, kind=kind, ts=ts, http_status=200) for _ in range(n)]
    )


@pytest.mark.django_db
def test_poll_budget_and_reserve_are_separate() -> None:
    account = make_account()  # limit 100, reserve 10, poll 90
    backfill(account, CallKind.POLL, 90)
    assert budget.try_acquire(account.id, CallKind.POLL) is None  # polls exhausted
    assert budget.try_acquire(account.id, CallKind.COMMAND) is not None  # reserve still there
    backfill(account, CallKind.COMMAND, 9)
    assert budget.try_acquire(account.id, CallKind.VERIFY) is None  # reserve exhausted
    s = budget.status(account)
    assert s.used == 100 and s.available_for_poll == 0 and s.available_for_reserve == 0


@pytest.mark.django_db
def test_window_is_sliding_and_reset_at_points_at_oldest_call() -> None:
    account = make_account()
    backfill(account, CallKind.POLL, 90, age_s=86400 + 5)  # outside the window
    assert budget.try_acquire(account.id, CallKind.POLL) is not None
    backfill(account, CallKind.POLL, 5, age_s=3600)
    s = budget.status(account)
    assert s.used == 6 and s.poll_used == 6
    assert (
        abs((s.reset_at - (timezone.now() + timedelta(seconds=86400 - 3600))).total_seconds()) < 5
    )


@pytest.mark.django_db
def test_short_window_brake() -> None:
    account = make_account(budget_limit=10000, short_limit=120, short_window_s=600)
    backfill(account, CallKind.POLL, 108)  # 90 % of 120
    assert budget.try_acquire(account.id, CallKind.POLL) is None
    backfill(account, CallKind.POLL, 0)
    ApiCall.objects.filter(provider_account=account).update(
        ts=timezone.now() - timedelta(seconds=601)
    )
    assert budget.try_acquire(account.id, CallKind.POLL) is not None


@pytest.mark.django_db
def test_finish_call_completes_the_ledger_row() -> None:
    account = make_account()
    call = budget.try_acquire(account.id, CallKind.DISCOVER)
    assert call is not None and call.http_status is None
    budget.finish_call(call, http_status=200, duration_ms=123)
    call.refresh_from_db()
    assert call.http_status == 200 and call.duration_ms == 123


@pytest.mark.django_db(transaction=True)
def test_fifty_concurrent_acquires_with_ten_available_give_exactly_ten() -> None:
    with system_context():
        account = make_account(budget_limit=100, budget_reserve_pct=10)
        backfill(account, CallKind.POLL, 80)  # 10 poll slots left
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with system_context():
                got = budget.try_acquire(account.id, CallKind.POLL) is not None
        finally:
            connection.close()
        with lock:
            results.append(got)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 50 and sum(results) == 10
    with system_context():
        assert ApiCall.objects.filter(provider_account=account).count() == 90


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, 86400 // 1233 + 1),  # ceil(86400 / (1233/1)) = 71 → floored to 71? no: max(71, 60) = 71
        (6, 421),  # ceil(86400 / (1233/6)) = ceil(420.4) = 421 (docs/06: ≈ 7 min)
        (50, 3504),
        (500, 35037),
    ],
)
def test_auto_interval(n: int, expected: int) -> None:
    account = ProviderAccount(
        budget_limit=1450,
        budget_window_s=86400,
        budget_reserve_pct=15,
        short_limit=120,
        short_window_s=600,
    )
    assert account.poll_budget == 1233
    assert budget.auto_interval_s(account, n) == expected


def test_interval_for_respects_manual_value_and_floors() -> None:
    account = ProviderAccount(
        budget_limit=1450,
        budget_window_s=86400,
        budget_reserve_pct=15,
        short_limit=120,
        short_window_s=600,
    )
    assert budget.interval_for(account, 6, None) == 421
    assert budget.interval_for(account, 6, 900) == 900
    assert budget.interval_for(account, 6, 10) == 60  # never below 60 s
