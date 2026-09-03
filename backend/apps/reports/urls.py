from django.urls import path

from .api import (
    DownloadView,
    FilesView,
    FileView,
    HtmlPreviewView,
    JobsView,
    PreviewView,
    SchedulesView,
    ScheduleView,
)

urlpatterns = [
    path("tenants/<str:tenant_id>/reports/preview", PreviewView.as_view(), name="report-preview"),
    path(
        "tenants/<str:tenant_id>/reports/preview.html",
        HtmlPreviewView.as_view(),
        name="report-preview-html",
    ),
    path("tenants/<str:tenant_id>/reports/jobs", JobsView.as_view(), name="report-jobs"),
    path("tenants/<str:tenant_id>/reports/files", FilesView.as_view(), name="report-files"),
    path(
        "tenants/<str:tenant_id>/reports/files/<str:file_id>",
        FileView.as_view(),
        name="report-file",
    ),
    path(
        "tenants/<str:tenant_id>/reports/files/<str:file_id>/download",
        DownloadView.as_view(),
        name="report-file-download",
    ),
    path(
        "tenants/<str:tenant_id>/report-schedules", SchedulesView.as_view(), name="report-schedules"
    ),
    path(
        "tenants/<str:tenant_id>/report-schedules/<str:schedule_id>",
        ScheduleView.as_view(),
        name="report-schedule",
    ),
]
