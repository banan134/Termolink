"""Devices API — docs/04 §Urządzenia."""

from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.exceptions import ApiError
from apps.tenants.permissions import IsOperator, current_user, forbidden, get_tenant_or_404

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
        device = services.get_device_or_404(tenant, device_id)
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


class DeviceHistoryView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        q = request.query_params
        feature = q.get("feature")
        prop = q.get("property", "value")
        if not feature:
            raise ApiError(
                "validation_error", "Brak parametru `feature`.", fields={"feature": ["wymagane"]}
            )
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
        resolution = q.get("resolution")
        if resolution not in (None, "raw", "1h", "1d"):
            raise ApiError(
                "validation_error", "resolution: raw|1h|1d", fields={"resolution": ["raw|1h|1d"]}
            )
        try:
            max_points = min(int(q.get("max_points", 2000)), 20000)
        except ValueError as exc:
            raise ApiError(
                "validation_error", "max_points", fields={"max_points": ["liczba"]}
            ) from exc
        return Response(
            services.history(
                device,
                feature=feature,
                prop=prop,
                start=start,
                end=end,
                resolution=resolution,
                max_points=max_points,
            )
        )


class DeviceStatusHistoryView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = services.get_device_or_404(tenant, device_id)
        rows = services.status_history(device)
        return Response({"results": rows, "count": len(rows)})
