from django.urls import path

from .api import JobDetailView

urlpatterns = [
    path("jobs/<str:job_id>", JobDetailView.as_view(), name="job-detail"),
]
