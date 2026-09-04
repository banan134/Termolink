"""Devices API — docs/04 §Urządzenia."""

from datetime import datetime, timedelta
from typing import Any

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.exceptions import ApiError
from apps.tenants.permissions import (
    IsOperator,
    IsSuperadmin,
    current_user,
    forbidden,
    get_tenant_or_404,
)

from . import history as history_mod
from . import labels as label_dict
from . import services
from .models import Device, DeviceMode


class ExternalIdsSerializer(serializers.Serializer[dict[str, str]]):
    installationId = serializers.CharField(max_length=64)  # noqa: N815 — API field names
    gatewaySerial = serializers.CharField(max_length=64)  # noqa: N815
    deviceId = serializers.CharField(max_length=64)  # noqa: N815


class DeviceCreateSerializer(serializers.Serializer[dict[str, Any]]):
    provider_account_id = serializers.UUIDField()
    external_ids = ExternalIdsSerializer()
    display_name = serializers.CharField(max_length=120)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=500
    )
    location_text = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=200
    )
    lat = serializers.DecimalField(required=False, allow_null=True, max_digits=9, decimal_places=6)
    lon = serializers.DecimalField(required=False, allow_null=True, max_digits=9, decimal_places=6)
    mode = serializers.ChoiceField(choices=DeviceMode.choices, required=False)
    poll_interval_s = serializers.IntegerField(
        required=False, allow_null=True, min_value=60, max_value=86400
    )


class DevicePatchSerializer(serializers.Serializer[dict[str, Any]]):
    display_name = serializers.CharField(required=False, max_length=120)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=500
    )
    location_text = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=200
    )
    lat = serializers.DecimalField(required=False, allow_null=True, max_digits=9, decimal_places=6)
    lon = serializers.DecimalField(required=False, allow_null=True, max_digits=9, decimal_places=6)
    mode = serializers.ChoiceField(choices=DeviceMode.choices, required=False)
    poll_interval_s = serializers.IntegerField(
        required=False, allow_null=True, min_value=60, max_value=86400
    )
    commands_per_hour_limit = serializers.IntegerField(required=False, min_value=0, max_value=1000)


def _not_tenant_user(request: Request) -> None:
    if current_user(request).role == Role.TENANT_USER:
        raise forbidden()


class DeviceListView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        devices = list(Device.objects.filter(tenant=tenant, archived_at__isnull=True))
        highlights = services.highlights_for(devices)
        rows = [services.card(d, highlights.get(d.id, [])) for d in devices]
        return Response({"results": rows, "count": len(rows)})

    @extend_schema(request=DeviceCreateSerializer, responses={201: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        if not IsOperator().has_permission(request, self):
            raise forbidden()
        data = DeviceCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device = services.create_device(
            request._request, actor=current_user(request), tenant=tenant, data=data.validated_data
        )
        return Response(
            services.details(current_user(request), device), status=status.HTTP_201_CREATED
        )


class DeviceDetailView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        return Response(services.details(current_user(request), device))

    @extend_schema(request=DevicePatchSerializer, responses={200: None})
    def patch(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        user = current_user(request)
        if user.role == Role.TENANT_USER:
            raise forbidden()
        data = DevicePatchSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        device = services.update_device(
            request._request, actor=user, device=device, data=data.validated_data
        )
        return Response(services.details(user, device))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        if not IsOperator().has_permission(request, self):
            raise forbidden()
        permanent = request.query_params.get("permanent") in ("1", "true")
        device = services.get_device_or_404(tenant, device_id, include_archived=permanent)
        if permanent:
            services.delete_device(request._request, actor=current_user(request), device=device)
        else:
            services.archive_device(request._request, actor=current_user(request), device=device)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceRefreshView(APIView):
    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        _not_tenant_user(request)
        device = services.get_device_or_404(tenant, device_id)
        job = services.refresh_now(request._request, actor=current_user(request), device=device)
        return Response({"job_id": str(job.public_id)}, status=status.HTTP_202_ACCEPTED)


class DeviceFeaturesView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        rows = services.features(device)
        return Response({"results": rows, "count": len(rows)})


def _parse_range(q: Any) -> tuple[datetime, datetime]:
    # "+" in ISO offsets arrives as a space unless the client URL-encodes it
    end = parse_datetime(q["to"].replace(" ", "+")) if q.get("to") else timezone.now()
    start = parse_datetime(q["from"].replace(" ", "+")) if q.get("from") else None
    if (q.get("to") and end is None) or (q.get("from") and start is None):
        raise ApiError(
            "validation_error", "Nieprawidłowa data (ISO 8601).", fields={"from": ["ISO 8601"]}
        )
    assert end is not None
    if start is None:
        start = end - timedelta(days=7)
    return start, end


def _parse_resolution(q: Any) -> str | None:
    resolution = q.get("resolution")
    if resolution not in (None, "raw", "1h", "1d"):
        raise ApiError(
            "validation_error", "resolution: raw|1h|1d", fields={"resolution": ["raw|1h|1d"]}
        )
    return str(resolution) if resolution else None


def _parse_max_points(q: Any) -> int:
    try:
        return min(int(q.get("max_points", 2000)), 20000)
    except ValueError as exc:
        raise ApiError("validation_error", "max_points", fields={"max_points": ["liczba"]}) from exc


class DeviceHistoryView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        q = request.query_params
        feature = q.get("feature")
        if not feature:
            raise ApiError(
                "validation_error", "Brak parametru `feature`.", fields={"feature": ["wymagane"]}
            )
        start, end = _parse_range(q)
        return Response(
            services.history(
                device,
                feature=feature,
                prop=q.get("property", "value"),
                start=start,
                end=end,
                resolution=_parse_resolution(q),
                max_points=_parse_max_points(q),
            )
        )


class DeviceHistoryCsvView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> HttpResponse:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        q = request.query_params
        feature = q.get("feature")
        if not feature:
            raise ApiError(
                "validation_error", "Brak parametru `feature`.", fields={"feature": ["wymagane"]}
            )
        start, end = _parse_range(q)
        result = services.history(
            device,
            feature=feature,
            prop=q.get("property", "value"),
            start=start,
            end=end,
            resolution=_parse_resolution(q),
            max_points=20000,
        )
        body = history_mod.to_csv(result)
        name = f"termolink_{device.display_name}_{feature}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
        response = HttpResponse(body, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{safe}"'
        return response


class SeriesSerializer(serializers.Serializer[dict[str, str]]):
    device_id = serializers.UUIDField()
    feature = serializers.CharField(max_length=200)
    property = serializers.CharField(max_length=100, default="value")


class HistoryMultiSerializer(serializers.Serializer[dict[str, Any]]):
    series = serializers.ListField(child=SeriesSerializer(), min_length=1, max_length=6)
    from_ = serializers.DateTimeField(required=False, source="from")
    to = serializers.DateTimeField(required=False)
    resolution = serializers.ChoiceField(choices=["raw", "1h", "1d"], required=False)
    max_points = serializers.IntegerField(
        required=False, min_value=10, max_value=20000, default=2000
    )

    def get_fields(self) -> Any:
        fields = super().get_fields()
        fields["from"] = fields.pop("from_")
        fields["from"].source = None
        return fields


class HistoryMultiView(APIView):
    """docs/04: up to 6 series for comparisons in the chart explorer."""

    @extend_schema(request=HistoryMultiSerializer, responses={200: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        data = HistoryMultiSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        end = v.get("to") or timezone.now()
        start = v.get("from") or end - timedelta(days=7)
        results = []
        for item in v["series"]:
            device = services.get_device_or_404(tenant, item["device_id"])
            results.append(
                services.history(
                    device,
                    feature=item["feature"],
                    prop=item.get("property", "value"),
                    start=start,
                    end=end,
                    resolution=v.get("resolution"),
                    max_points=v.get("max_points", 2000),
                )
            )
        return Response({"results": results, "count": len(results)})


class DeviceMessagesView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        return Response(services.messages(device))


class FeatureLabelSerializer(serializers.Serializer[dict[str, Any]]):
    pattern = serializers.CharField(max_length=200)
    label_pl = serializers.CharField(allow_blank=True, max_length=200)
    description_pl = serializers.CharField(
        allow_blank=True, required=False, default="", max_length=500
    )
    group_key = serializers.CharField(
        allow_blank=True, allow_null=True, required=False, max_length=50
    )
    sort = serializers.IntegerField(required=False, default=100)
    highlight = serializers.BooleanField(required=False, default=False)
    report_default = serializers.BooleanField(required=False, default=False)
    command_property_map = serializers.DictField(required=False, default=dict)


class FeatureLabelsView(APIView):
    """GET/PUT /admin/feature-labels — global dictionary, superadmin only (docs/04)."""

    permission_classes = [IsSuperadmin]

    @extend_schema(responses=FeatureLabelSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = label_dict.as_rows()
        return Response({"results": rows, "count": len(rows)})

    @extend_schema(request=FeatureLabelSerializer(many=True), responses={200: None})
    def put(self, request: Request) -> Response:
        data = FeatureLabelSerializer(data=request.data, many=True)
        data.is_valid(raise_exception=True)
        items = list(data.validated_data)
        patterns = [i["pattern"] for i in items]
        if len(patterns) != len(set(patterns)):
            raise ApiError(
                "validation_error", "Powtórzone wzorce.", fields={"pattern": ["duplikat"]}
            )
        count = label_dict.bulk_replace(items)
        from apps.audit.services import audit

        audit("feature_labels.replaced", request=request._request, details={"count": count})
        return Response({"count": count})


class DeviceStatusHistoryView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        rows = services.status_history(device)
        return Response({"results": rows, "count": len(rows)})
