"""Alerts API — docs/04 §Alarmy."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.exceptions import ApiError
from apps.devices import services as device_services
from apps.tenants.permissions import IsOperator, current_user, get_tenant_or_404

from . import services
from .models import CONFIGURABLE_TYPES, Alert, AlertRule


def _paginate(request: Request) -> tuple[int, int]:
    q = request.query_params
    try:
        page_size = min(int(q.get("page_size", 50)), 200)
        page = max(int(q.get("page", 1)), 1)
    except ValueError as exc:
        raise ApiError("validation_error", "page/page_size", fields={"page": ["liczba"]}) from exc
    return page, page_size


def _require_writer(request: Request) -> None:
    user = current_user(request)
    if user.role == Role.TENANT_USER:
        raise ApiError("forbidden", "Brak uprawnień.", status_code=403)


class AlertListView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        qs = Alert.objects.filter(tenant=tenant).select_related("device", "acknowledged_by")
        q = request.query_params
        if q.get("open") in ("1", "true"):
            qs = qs.filter(closed_at__isnull=True)
        if q.get("device"):
            qs = qs.filter(device_id=q["device"])
        page, page_size = _paginate(request)
        total = qs.count()
        rows = qs[(page - 1) * page_size : page * page_size]
        return Response(
            {
                "results": [services.payload(a) for a in rows],
                "count": total,
                "open_count": Alert.objects.filter(tenant=tenant, closed_at__isnull=True).count(),
            }
        )


class AlertAckSerializer(serializers.Serializer[dict[str, bool]]):
    acknowledged = serializers.BooleanField()


class AlertDetailView(APIView):
    @extend_schema(request=AlertAckSerializer, responses={200: None})
    def patch(self, request: Request, tenant_id: str, alert_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        alert = Alert.objects.filter(tenant=tenant, id=alert_id).select_related("device").first()
        if alert is None:
            raise ApiError("not_found", "Nie znaleziono.", status_code=404)
        data = AlertAckSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if data.validated_data["acknowledged"]:
            services.acknowledge(alert, current_user(request))
        return Response(services.payload(alert))


class RuleSerializer(serializers.Serializer[dict[str, Any]]):
    device_id = serializers.UUIDField(required=False, allow_null=True)
    type = serializers.ChoiceField(choices=[t.value for t in CONFIGURABLE_TYPES])
    config = serializers.DictField(required=False, default=dict)
    enabled = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        config = attrs.get("config") or {}
        errors: dict[str, list[str]] = {}
        if attrs.get("type") == "device_offline":
            minutes = config.get("minutes", 30)
            if not isinstance(minutes, int | float) or not 1 <= minutes <= 10080:
                errors["minutes"] = ["1–10080 minut."]
        if attrs.get("type") == "value_out_of_range":
            if not config.get("feature"):
                errors["feature"] = ["Wymagana cecha."]
            lo, hi = config.get("min"), config.get("max")
            if lo is None and hi is None:
                errors["min"] = ["Podaj min lub max."]
            if lo is not None and hi is not None and lo > hi:
                errors["min"] = ["min > max."]
        if errors:
            raise ApiError("validation_error", "Błędna reguła.", fields=errors)
        return attrs


class RuleListView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        rules = AlertRule.objects.filter(tenant=tenant).select_related("device")
        return Response({"results": [services.rule_payload(r) for r in rules]})

    @extend_schema(request=RuleSerializer, responses={201: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_writer(request)
        data = RuleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        device = (
            device_services.get_device_or_404(tenant, str(v["device_id"]))
            if v.get("device_id")
            else None
        )
        rule = AlertRule.objects.create(
            tenant=tenant,
            device=device,
            type=v["type"],
            config=v.get("config") or {},
            enabled=v.get("enabled", True),
        )
        return Response(services.rule_payload(rule), status=status.HTTP_201_CREATED)


class RuleDetailView(APIView):
    def _get(self, request: Request, tenant_id: str, rule_id: str) -> AlertRule:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_writer(request)
        rule = AlertRule.objects.filter(tenant=tenant, id=rule_id).select_related("device").first()
        if rule is None:
            raise ApiError("not_found", "Nie znaleziono.", status_code=404)
        return rule

    @extend_schema(request=RuleSerializer, responses={200: None})
    def patch(self, request: Request, tenant_id: str, rule_id: str) -> Response:
        rule = self._get(request, tenant_id, rule_id)
        merged = {
            "type": rule.type,
            "config": rule.config,
            "enabled": rule.enabled,
            "device_id": rule.device_id,
            **(request.data if isinstance(request.data, dict) else {}),
        }
        data = RuleSerializer(data=merged)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        rule.config = v.get("config") or {}
        rule.enabled = v.get("enabled", rule.enabled)
        rule.save(update_fields=["config", "enabled", "updated_at"])
        return Response(services.rule_payload(rule))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, tenant_id: str, rule_id: str) -> Response:
        rule = self._get(request, tenant_id, rule_id)
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminAlertsView(APIView):
    """Operator: open alerts across all tenants (incl. tenant-less worker alerts)."""

    permission_classes = [IsOperator]

    @extend_schema(responses={200: None})
    def get(self, request: Request) -> Response:
        qs = Alert.objects.filter(closed_at__isnull=True).select_related(
            "device", "tenant", "acknowledged_by"
        )
        return Response(
            {
                "results": [
                    {
                        **services.payload(a),
                        "tenant_name": a.tenant.name if a.tenant is not None else None,
                    }
                    for a in qs[:200]
                ],
                "count": qs.count(),
            }
        )
