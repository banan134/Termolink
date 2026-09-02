"""Operator API for tenants (docs/04 §Operator: klienci) + tenant-scoped users/invitations."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Invitation, Role, User

from . import services
from .models import Tenant, TenantMembership, TenantType
from .permissions import (
    IsOperator,
    IsSuperadmin,
    current_user,
    get_tenant_or_404,
    require_tenant_admin_or_operator,
)


# ---------- serializers ----------
class TenantSerializer(serializers.ModelSerializer[Tenant]):
    users_count = serializers.IntegerField(read_only=True)
    devices_count = serializers.IntegerField(read_only=True, default=0)  # stage 2
    online_count = serializers.IntegerField(read_only=True, default=0)  # stage 2

    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "type",
            "control_allowed",
            "report_header_text",
            "timezone",
            "created_at",
            "archived_at",
            "users_count",
            "devices_count",
            "online_count",
        ]
        read_only_fields = ["id", "created_at", "archived_at"]


class TenantWriteSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=200)
    type = serializers.ChoiceField(choices=TenantType.choices, required=False)
    control_allowed = serializers.BooleanField(required=False)
    report_header_text = serializers.CharField(required=False, allow_blank=True, max_length=200)
    timezone = serializers.CharField(required=False, max_length=64)


class TenantPatchSerializer(TenantWriteSerializer):
    name = serializers.CharField(max_length=200, required=False)


class UserRowSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "email", "role", "totp_enabled", "is_active", "last_login", "created_at"]


class InvitationRowSerializer(serializers.ModelSerializer[Invitation]):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "expires_at", "created_at"]


class InviteSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[Role.TENANT_ADMIN, Role.TENANT_USER])


class MembershipSerializer(serializers.ModelSerializer[TenantMembership]):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = TenantMembership
        fields = ["tenant_id", "tenant_name", "can_control", "created_at"]


class MembershipWriteSerializer(serializers.Serializer[dict[str, Any]]):
    tenant_id = serializers.UUIDField()
    can_control = serializers.BooleanField(default=False)


def _with_counts(tenant: Tenant) -> Tenant:
    tenant.users_count = User.objects.filter(tenant=tenant).count()  # type: ignore[attr-defined]
    return tenant


# ---------- /admin/tenants ----------
class AdminTenantListView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(responses=TenantSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = [_with_counts(t) for t in services.visible_tenants(request._request)]
        return Response({"results": TenantSerializer(rows, many=True).data, "count": len(rows)})

    @extend_schema(request=TenantWriteSerializer, responses={201: TenantSerializer})
    def post(self, request: Request) -> Response:
        data = TenantWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tenant = services.create_tenant(
            request._request, actor=current_user(request), **data.validated_data
        )
        return Response(TenantSerializer(_with_counts(tenant)).data, status=status.HTTP_201_CREATED)


class AdminTenantDetailView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(responses=TenantSerializer)
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        return Response(TenantSerializer(_with_counts(tenant)).data)

    @extend_schema(request=TenantPatchSerializer, responses=TenantSerializer)
    def patch(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        data = TenantPatchSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        tenant = services.update_tenant(
            request._request, actor=current_user(request), tenant=tenant, **data.validated_data
        )
        return Response(TenantSerializer(_with_counts(tenant)).data)


# ---------- users & invitations (operator via /admin, tenant_admin via /tenants) ----------
class TenantUsersView(APIView):
    @extend_schema(responses=UserRowSerializer(many=True))
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        require_tenant_admin_or_operator(request, tenant)
        users = services.tenant_users(tenant)
        invitations = services.pending_invitations(tenant)
        return Response(
            {
                "results": UserRowSerializer(users, many=True).data,
                "count": len(users),
                "invitations": InvitationRowSerializer(invitations, many=True).data,
            }
        )


class TenantInvitationsView(APIView):
    @extend_schema(request=InviteSerializer, responses={201: InvitationRowSerializer})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        actor = require_tenant_admin_or_operator(request, tenant)
        data = InviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invitation = services.invite_to_tenant(
            request._request,
            actor=actor,
            tenant=tenant,
            email=data.validated_data["email"],
            role=data.validated_data["role"],
        )
        return Response(InvitationRowSerializer(invitation).data, status=status.HTTP_201_CREATED)


class AdminTenantUsersView(TenantUsersView):
    permission_classes = [IsOperator]


class AdminTenantInvitationsView(TenantInvitationsView):
    permission_classes = [IsOperator]


# ---------- /admin/technicians/{id}/memberships ----------
class TechnicianMembershipsView(APIView):
    permission_classes = [IsSuperadmin]

    @extend_schema(responses=MembershipSerializer(many=True))
    def get(self, request: Request, user_id: str) -> Response:
        tech = services.technician_or_404(user_id)
        rows = services.list_memberships(tech)
        return Response({"results": MembershipSerializer(rows, many=True).data, "count": len(rows)})

    @extend_schema(request=MembershipWriteSerializer, responses={201: MembershipSerializer})
    def post(self, request: Request, user_id: str) -> Response:
        tech = services.technician_or_404(user_id)
        data = MembershipWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tenant = get_tenant_or_404(request, data.validated_data["tenant_id"])
        row = services.set_membership(
            request._request,
            actor=current_user(request),
            technician=tech,
            tenant=tenant,
            can_control=data.validated_data["can_control"],
        )
        return Response(MembershipSerializer(row).data, status=status.HTTP_201_CREATED)


class TechnicianMembershipDetailView(APIView):
    permission_classes = [IsSuperadmin]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, user_id: str, tenant_id: str) -> Response:
        tech = services.technician_or_404(user_id)
        tenant = get_tenant_or_404(request, tenant_id)
        services.remove_membership(
            request._request, actor=current_user(request), technician=tech, tenant=tenant
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminTechniciansView(APIView):
    permission_classes = [IsSuperadmin]

    @extend_schema(responses=UserRowSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = list(User.objects.filter(role=Role.TECHNICIAN).order_by("email"))
        return Response({"results": UserRowSerializer(rows, many=True).data, "count": len(rows)})
