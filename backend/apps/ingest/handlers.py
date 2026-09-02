"""Built-in job handlers. Domain handlers (poll, discover, execute_command…) register in
their own apps from stage 2 on."""

from typing import Any

from .models import Job
from .queue import job_handler


@job_handler("noop")
def noop(job: Job) -> dict[str, Any]:
    """Diagnostics: proves the queue → worker → result path works."""
    return {"echo": job.payload}


@job_handler("fail")
def always_fail(job: Job) -> dict[str, Any]:
    raise RuntimeError(job.payload.get("message", "intentional failure"))
