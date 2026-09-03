"""Control API — docs/04 §Sterowanie."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.exceptions import ApiError
from apps.devices import services as device_services
from apps.tenants.permissions import current_user, get_tenant_or_404

from . import services
from .models import Command


class CommandCreateSerializer(serializers.Serializer[dict[str, Any]]):
    feature_name = serializers.CharField(max_length=200)
    command_name = serializers.CharField(max_length=100)
    params = serializers.DictField(required=False, default=dict)


class ConfirmSerializer(serializers.Serializer[dict[str, bool]]):
    acknowledged = serializers.BooleanField()


class CommandThrottle(UserRateThrottle):
    scope = "commands"  # docs/08: /commands 30/h/user


class DeviceCommandsView(APIView):
    throttle_classes = [CommandThrottle]

    @extend_schema(request=CommandCreateSerializer, responses={201: None})
    def post(self, request: Request, tenant_id: str, device_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        device = device_services.get_device_or_404(tenant, device_id)
        data = CommandCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        command = services.create_draft(
            request._request,
            user=current_user(request),
            device=device,
            feature_name=data.validated_data["feature_name"],
            command_name=data.validated_data["command_name"],
            params=data.validated_data.get("params") or {},
        )
        return Response(services.payload(command), status=status.HTTP_201_CREATED)


class CommandConfirmView(APIView):
    @extend_schema(request=ConfirmSerializer, responses={200: None})
    def post(self, request: Request, tenant_id: str, command_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        data = ConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if not data.validated_data["acknowledged"]:
            raise ApiError(
                "validation_error", "Wymagane potwierdzenie.", fields={"acknowledged": ["wymagane"]}
            )
        command = services.get_command_or_404(tenant.id, command_id)
        command = services.confirm(request._request, user=current_user(request), command=command)
        return Response(services.payload(command))


class CommandDetailView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, command_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        command = services.get_command_or_404(tenant.id, command_id)
        body = services.payload(command)
        job = services.job_for(command)
        body["job"] = (
            {
                "kind": job.kind,
                "status": job.status,
                "error": job.last_error if job.status == "failed" else None,
            }
            if job
            else None
        )
        return Response(body)


class CommandListView(APIView):
    """Dziennik zmian (docs/04): filters device, status, from/to; newest first."""

    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        qs = Command.objects.filter(tenant=tenant).select_related("device", "user")
        q = request.query_params
        if q.get("device"):
            qs = qs.filter(device_id=q["device"])
        if q.get("status"):
            qs = qs.filter(status=q["status"])
        try:
            page_size = min(int(q.get("page_size", 50)), 200)
            page = max(int(q.get("page", 1)), 1)
        except ValueError as exc:
            raise ApiError(
                "validation_error", "page/page_size", fields={"page": ["liczba"]}
            ) from exc
        total = qs.count()
        rows = [services.reconcile(c) for c in qs[(page - 1) * page_size : page * page_size]]
        return Response(
            {
                "results": [
                    {**services.payload(c), "device_name": c.device.display_name} for c in rows
                ],
                "count": total,
            }
        )
