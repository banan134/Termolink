"""Provider accounts API — docs/04 §Konta producentów."""

from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.views.decorators.http import require_GET
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.exceptions import ApiError
from apps.tenants.permissions import IsOperator, current_user, forbidden, get_tenant_or_404

from . import services
from .models import AccountStatus


class AuthorizeSerializer(serializers.Serializer[dict[str, str]]):
    label = serializers.CharField(required=False, allow_blank=True, max_length=100)  # type: ignore[assignment]


class AccountPatchSerializer(serializers.Serializer[dict[str, Any]]):
    label = serializers.CharField(required=False, allow_blank=True, max_length=100)  # type: ignore[assignment]
    budget_limit = serializers.IntegerField(required=False, min_value=10, max_value=100000)
    budget_reserve_pct = serializers.IntegerField(required=False, min_value=0, max_value=90)
    status = serializers.ChoiceField(choices=[AccountStatus.DISABLED], required=False)


def _require_read(request: Request) -> None:
    user = current_user(request)
    if user.role == Role.TENANT_USER:
        raise forbidden()


class ProviderAccountListView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_read(request)
        rows = [services.account_payload(a) for a in tenant.provider_accounts.all()]
        return Response({"results": rows, "count": len(rows)})


class ProviderAuthorizeView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(request=AuthorizeSerializer, responses={200: None})
    def post(self, request: Request, tenant_id: str, provider: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        data = AuthorizeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            url = services.start_authorization(
                request._request,
                actor=current_user(request),
                tenant=tenant,
                provider=provider,
                label=data.validated_data.get("label", ""),
            )
        except KeyError as exc:
            raise ApiError("unknown_provider", "Nieznany producent.", status_code=404) from exc
        return Response({"redirect_url": url})


class ProviderAccountDetailView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(request=AccountPatchSerializer, responses={200: None})
    def patch(self, request: Request, tenant_id: str, account_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        account = services.get_account_or_404(tenant, account_id)
        data = AccountPatchSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        account = services.update_account(
            request._request, actor=current_user(request), account=account, **data.validated_data
        )
        return Response(services.account_payload(account))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, tenant_id: str, account_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        account = services.get_account_or_404(tenant, account_id)
        services.disconnect_account(request._request, actor=current_user(request), account=account)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProviderDiscoverView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, tenant_id: str, account_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        account = services.get_account_or_404(tenant, account_id)
        job = services.enqueue_discover(
            request._request, actor=current_user(request), account=account
        )
        return Response({"job_id": str(job.public_id)}, status=status.HTTP_202_ACCEPTED)


class ProviderDiscoveredView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, account_id: str) -> Response:
        from apps.devices.models import Device, DiscoveredDevice

        tenant = get_tenant_or_404(request, tenant_id)
        account = services.get_account_or_404(tenant, account_id)
        added = {
            (d["installationId"], d["gatewaySerial"], d["deviceId"])
            for d in Device.objects.filter(
                provider_account=account, archived_at__isnull=True
            ).values_list("external_ids", flat=True)
        }
        tree: dict[str, dict[str, Any]] = {}
        for row in DiscoveredDevice.objects.filter(provider_account=account).order_by(
            "installation_id", "gateway_serial", "device_id"
        ):
            inst = tree.setdefault(
                row.installation_id, {"installation_id": row.installation_id, "gateways": {}}
            )
            gw = inst["gateways"].setdefault(
                row.gateway_serial, {"gateway_serial": row.gateway_serial, "devices": []}
            )
            gw["devices"].append(
                {
                    "device_id": row.device_id,
                    "model": row.model,
                    "device_type": row.device_type,
                    "online": row.online,
                    "seen_at": row.seen_at,
                    "already_added": (row.installation_id, row.gateway_serial, row.device_id)
                    in added,
                    "is_gateway": row.device_id == "gateway",
                }
            )
        installations = [
            {**inst, "gateways": list(inst["gateways"].values())} for inst in tree.values()
        ]
        return Response(
            {
                "installations": installations,
                "discovered_at": max(
                    (r.seen_at for r in DiscoveredDevice.objects.filter(provider_account=account)),
                    default=None,
                ),
            }
        )


@require_GET
def oauth_callback(request: HttpRequest, provider: str) -> HttpResponseRedirect:
    """GET /oauth/<provider>/callback — outside /api; ends with a redirect to the UI (docs/04)."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    try:
        tenant, account, error = services.finish_authorization(
            request, provider=provider, params=dict(request.GET.items())
        )
    except ApiError as exc:
        return HttpResponseRedirect(
            f"{base}/admin/tenants?provider={provider}&error={exc.error_code}"
        )
    except KeyError:
        return HttpResponseRedirect(
            f"{base}/admin/tenants?provider={provider}&error=unknown_provider"
        )
    if error:
        return HttpResponseRedirect(
            f"{base}/admin/tenants/{tenant.id}?provider={provider}&error={error}"
        )
    connected = account.id if account else ""
    return HttpResponseRedirect(
        f"{base}/admin/tenants/{tenant.id}?provider={provider}&connected={connected}"
    )
