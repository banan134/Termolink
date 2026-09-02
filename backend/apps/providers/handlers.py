"""Job handlers owned by the providers app."""

from typing import Any

from apps.ingest.models import Job
from apps.ingest.queue import job_handler

from .models import ProviderAccount
from .services import run_discover


@job_handler("discover")
def discover(job: Job) -> dict[str, Any]:
    account = ProviderAccount.objects.get(id=job.payload["account_id"])
    count = run_discover(account)
    return {"devices": count}
