"""GET /api/v1/jobs/{id} — job status for UI polling (docs/04 §Zadania). RLS scopes rows."""

from uuid import UUID

from django.db.models import Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ApiError
from apps.tenants.context import ROLE_OPERATOR, ROLE_TENANT, TenantContext

from .models import Job


def visible_jobs(request: Request) -> QuerySet[Job]:
    """Explicit scoping on top of RLS (docs/04: permissions enforced in views and services)."""
    ctx: TenantContext | None = getattr(request._request, "tenant_context", None)
    if ctx is None:
        return Job.objects.none()
    if ctx.role == ROLE_TENANT and ctx.tenant_id is not None:
        return Job.objects.filter(tenant_id=ctx.tenant_id)
    if ctx.role == ROLE_OPERATOR:
        return Job.objects.filter(Q(tenant_id__in=ctx.allowed_tenants) | Q(tenant__isnull=True))
    return Job.objects.none()


class JobSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    result = serializers.JSONField(allow_null=True)
    error = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)


class JobDetailView(APIView):
    @extend_schema(responses=JobSerializer)
    def get(self, request: Request, job_id: str) -> Response:
        try:
            job = visible_jobs(request).get(public_id=UUID(job_id))
        except (Job.DoesNotExist, ValueError) as exc:
            raise ApiError("not_found", "Zadanie nie istnieje.", status_code=404) from exc
        return Response(
            {
                "id": str(job.public_id),
                "kind": job.kind,
                "status": job.status,
                "result": job.result,
                "error": job.last_error if job.status == "failed" else None,
                "created_at": job.created_at,
                "finished_at": job.finished_at,
            }
        )
