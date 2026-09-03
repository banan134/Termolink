"""Job handlers: execute_command, verify_command (docs/07)."""

from typing import Any

from apps.ingest.models import Job
from apps.ingest.queue import job_handler

from .models import Command
from .services import execute, verify


def _load(job: Job) -> Command:
    return Command.objects.select_related(
        "device", "device__provider_account", "device__tenant", "tenant", "user"
    ).get(id=job.payload["command_id"])


@job_handler("execute_command")
def execute_command(job: Job) -> dict[str, Any]:
    return execute(_load(job))


@job_handler("verify_command")
def verify_command(job: Job) -> dict[str, Any]:
    return verify(_load(job))
