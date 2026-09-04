"""Operator overview (docs/09 §Panel operatora): every visible customer's devices in one payload,
read only from the database."""

from dataclasses import asdict
from typing import Any

from django.db.models import Count, Q
from django.http import HttpRequest

from apps.alerts.models import Alert
from apps.devices.models import Device, DeviceStatus
from apps.devices.services import card, highlights_for
from apps.providers import budget
from apps.providers.models import ProviderAccount
from apps.tenants.services import visible_tenants


def build(request: HttpRequest) -> dict[str, Any]:
    tenants = visible_tenants(request)
    tenant_ids = [t.id for t in tenants]
    devices = list(
        Device.objects.filter(tenant_id__in=tenant_ids, archived_at__isnull=True)
        .select_related("tenant", "provider_account")
        .order_by("tenant__name", "display_name")
    )
    open_alerts = dict(
        Alert.objects.filter(device_id__in=[d.id for d in devices], closed_at__isnull=True)
        .values_list("device_id")
        .annotate(n=Count("id"))
        .values_list("device_id", "n")
    )
    highlights = highlights_for(devices)
    by_tenant: dict[Any, list[dict[str, Any]]] = {}
    for d in devices:
        row = card(d, highlights.get(d.id, []))
        row.update(
            {
                "tenant_id": str(d.tenant_id),
                "tenant_name": d.tenant.name,
                "lat": float(d.lat) if d.lat is not None else None,
                "lon": float(d.lon) if d.lon is not None else None,
                "open_alerts": int(open_alerts.get(d.id, 0)),
            }
        )
        by_tenant.setdefault(d.tenant_id, []).append(row)
    accounts = []
    for a in ProviderAccount.objects.filter(tenant_id__in=tenant_ids).select_related("tenant"):
        st = budget.status(a)
        accounts.append(
            {
                "id": str(a.id),
                "tenant_id": str(a.tenant_id),
                "tenant_name": a.tenant.name,
                "label": a.label,
                "provider": a.provider,
                "status": a.status,
                "budget": asdict(st),
            }
        )
    counts = {s: 0 for s in DeviceStatus.values}
    for d in devices:
        counts[d.status] = counts.get(d.status, 0) + 1
    operator_alerts = Alert.objects.filter(closed_at__isnull=True).filter(
        Q(tenant_id__in=tenant_ids) | Q(tenant_id__isnull=True)
    )
    return {
        "totals": {
            "tenants": len(tenants),
            "devices": len(devices),
            "by_status": counts,
            "open_alerts": operator_alerts.count(),
            "control_mode": sum(1 for d in devices if d.mode == "control"),
        },
        "tenants": [
            {
                "id": str(t.id),
                "name": t.name,
                "control_allowed": t.control_allowed,
                "devices": by_tenant.get(t.id, []),
                "open_alerts": sum(r["open_alerts"] for r in by_tenant.get(t.id, [])),
            }
            for t in tenants
        ],
        "accounts": accounts,
    }
