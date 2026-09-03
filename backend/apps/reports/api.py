"""Reports API — docs/04 §Raporty."""

from pathlib import Path
from typing import Any

from croniter import croniter
from django.conf import settings
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.core.exceptions import ApiError
from apps.devices.models import Device
from apps.tenants.permissions import current_user, get_tenant_or_404

from . import jobs, render, services
from .models import FileStatus, Period, ReportFile, ReportFormat, ReportSchedule, ReportType


def _body(request: Request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _require_writer(request: Request) -> None:
    if current_user(request).role == Role.TENANT_USER:
        raise ApiError("forbidden", "Brak uprawnień.", status_code=403)


class PreviewView(APIView):
    @extend_schema(request=None, responses={200: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        params = services.parse_params(tenant, _body(request))
        return Response(services.build(tenant, params))


class JobsView(APIView):
    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        fmt = _body(request).get("format")
        if fmt not in ReportFormat.values:
            raise ApiError(
                "validation_error", "format: pdf|csv", fields={"format": ["pdf lub csv"]}
            )
        params = services.parse_params(tenant, _body(request))  # validates before queueing
        body = {
            k: _body(request).get(k)
            for k in ("report_type", "device_ids", "from", "to", "resolution", "features")
        }
        file, job = jobs.request_file(
            tenant=tenant,
            report_type=params.report_type,
            params=body,
            fmt=fmt,
            requested_by=current_user(request),
        )
        return Response(
            {"job_id": str(job.public_id), "file_id": str(file.id)}, status=status.HTTP_202_ACCEPTED
        )


def file_payload(f: ReportFile) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "report_type": f.report_type,
        "format": f.format,
        "status": f.status,
        "error": f.error,
        "params": f.params,
        "size_bytes": f.size_bytes,
        "filename": f.filename,
        "schedule_id": str(f.schedule_id) if f.schedule_id else None,
        "schedule_name": f.schedule.name if f.schedule else None,
        "requested_by": f.requested_by.email if f.requested_by else None,
        "created_at": f.created_at,
        "finished_at": f.finished_at,
        "expires_at": f.expires_at,
    }


class FilesView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        rows = ReportFile.objects.filter(tenant=tenant).select_related("schedule", "requested_by")[
            :100
        ]
        return Response({"results": [file_payload(f) for f in rows]})


class FileView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, file_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        f = (
            ReportFile.objects.filter(tenant=tenant, id=file_id)
            .select_related("schedule", "requested_by")
            .first()
        )
        if f is None:
            raise ApiError("not_found", "Nie znaleziono.", status_code=404)
        return Response(file_payload(f))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, tenant_id: str, file_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_writer(request)
        f = ReportFile.objects.filter(tenant=tenant, id=file_id).first()
        if f is None:
            raise ApiError("not_found", "Nie znaleziono.", status_code=404)
        if f.file_path:
            path = Path(settings.MEDIA_ROOT) / f.file_path
            if path.exists():
                path.unlink()
        f.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DownloadView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str, file_id: str) -> FileResponse:
        tenant = get_tenant_or_404(request, tenant_id)
        f = ReportFile.objects.filter(tenant=tenant, id=file_id).first()
        if f is None or f.status != FileStatus.DONE or not f.file_path:
            raise ApiError("not_found", "Plik nie jest gotowy.", status_code=404)
        path = Path(settings.MEDIA_ROOT) / f.file_path
        if not path.exists():
            raise ApiError("not_found", "Plik wygasł.", status_code=404)
        content_type = (
            "application/pdf" if f.format == ReportFormat.PDF else "text/csv; charset=utf-8"
        )
        response = FileResponse(
            path.open("rb"), content_type=content_type, as_attachment=True, filename=f.filename
        )
        return response


class ScheduleSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=120)
    report_type = serializers.ChoiceField(choices=ReportType.values)
    device_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    features = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    period = serializers.ChoiceField(
        choices=Period.values, required=False, default=Period.LAST_MONTH
    )
    resolution = serializers.ChoiceField(
        choices=["auto", "raw", "1h", "1d"], required=False, default="auto"
    )
    format = serializers.ChoiceField(
        choices=ReportFormat.values, required=False, default=ReportFormat.PDF
    )
    recipients = serializers.ListField(child=serializers.EmailField(), required=False, default=list)
    cron = serializers.CharField(required=False, default="0 6 1 * *")
    enabled = serializers.BooleanField(required=False, default=True)

    def validate_cron(self, value: str) -> str:
        if not croniter.is_valid(value):
            raise serializers.ValidationError("Błędne wyrażenie cron (5 pól).")
        return value


def schedule_payload(s: ReportSchedule) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "report_type": s.report_type,
        "device_ids": [str(d) for d in s.device_ids],
        "features": list(s.features),
        "period": s.period,
        "resolution": s.resolution,
        "format": s.format,
        "recipients": list(s.recipients),
        "cron": s.cron,
        "enabled": s.enabled,
        "last_run_at": s.last_run_at,
        "created_at": s.created_at,
    }


def _apply(tenant: Any, s: ReportSchedule, v: dict[str, Any]) -> ReportSchedule:
    ids = [str(d) for d in v["device_ids"]]
    if Device.objects.filter(tenant=tenant, id__in=ids).count() != len(set(ids)):
        raise ApiError("not_found", "Nie znaleziono urządzenia.", status_code=404)
    s.name = v["name"]
    s.report_type = v["report_type"]
    s.device_ids = list(v["device_ids"])
    s.features = list(v.get("features") or [])
    s.period = v.get("period", Period.LAST_MONTH)
    s.resolution = v.get("resolution", "auto")
    s.format = v.get("format", ReportFormat.PDF)
    s.recipients = list(v.get("recipients") or [])
    s.cron = v.get("cron", "0 6 1 * *")
    s.enabled = v.get("enabled", True)
    s.save()
    return s


class SchedulesView(APIView):
    @extend_schema(responses={200: None})
    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        return Response(
            {"results": [schedule_payload(s) for s in ReportSchedule.objects.filter(tenant=tenant)]}
        )

    @extend_schema(request=ScheduleSerializer, responses={201: None})
    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_writer(request)
        data = ScheduleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        s = _apply(
            tenant,
            ReportSchedule(tenant=tenant, created_by=current_user(request)),
            data.validated_data,
        )
        return Response(schedule_payload(s), status=status.HTTP_201_CREATED)


class ScheduleView(APIView):
    def _get(
        self, request: Request, tenant_id: str, schedule_id: str
    ) -> tuple[Any, ReportSchedule]:
        tenant = get_tenant_or_404(request, tenant_id)
        _require_writer(request)
        s = ReportSchedule.objects.filter(tenant=tenant, id=schedule_id).first()
        if s is None:
            raise ApiError("not_found", "Nie znaleziono.", status_code=404)
        return tenant, s

    @extend_schema(request=ScheduleSerializer, responses={200: None})
    def patch(self, request: Request, tenant_id: str, schedule_id: str) -> Response:
        tenant, s = self._get(request, tenant_id, schedule_id)
        merged = {**schedule_payload(s), **(request.data if isinstance(request.data, dict) else {})}
        data = ScheduleSerializer(data=merged)
        data.is_valid(raise_exception=True)
        return Response(schedule_payload(_apply(tenant, s, data.validated_data)))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, tenant_id: str, schedule_id: str) -> Response:
        _, s = self._get(request, tenant_id, schedule_id)
        s.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, tenant_id: str, schedule_id: str) -> Response:
        """Run now (uses the schedule's period)."""
        tenant, s = self._get(request, tenant_id, schedule_id)
        start, end = services.period_range(s.period, tenant.timezone)
        params = {
            "report_type": s.report_type,
            "device_ids": [str(d) for d in s.device_ids],
            "from": start.isoformat(),
            "to": end.isoformat(),
            "resolution": s.resolution,
            "features": list(s.features),
        }
        file, job = jobs.request_file(
            tenant=tenant,
            report_type=s.report_type,
            params=params,
            fmt=s.format,
            requested_by=current_user(request),
            schedule=s,
        )
        return Response(
            {"job_id": str(job.public_id), "file_id": str(file.id)}, status=status.HTTP_202_ACCEPTED
        )


class HtmlPreviewView(APIView):
    """Operator-only: the HTML the PDF is rendered from (debugging the template)."""

    @extend_schema(request=None, responses={200: None})
    def post(self, request: Request, tenant_id: str) -> Any:
        from django.http import HttpResponse

        tenant = get_tenant_or_404(request, tenant_id)
        if not current_user(request).is_operator:
            raise ApiError("forbidden", "Brak uprawnień.", status_code=403)
        params = services.parse_params(tenant, _body(request))
        return HttpResponse(render.render_html(services.build(tenant, params), tenant))
