"""Built-in job handlers. Domain handlers register in their own apps (providers: discover)."""

from typing import Any

from apps.devices.models import Device

from .models import Job
from .queue import job_handler


@job_handler("noop")
def noop(job: Job) -> dict[str, Any]:
    """Diagnostics: proves the queue → worker → result path works."""
    return {"echo": job.payload}


@job_handler("fail")
def always_fail(job: Job) -> dict[str, Any]:
    raise RuntimeError(job.payload.get("message", "intentional failure"))


@job_handler("poll")
def poll(job: Job) -> dict[str, Any]:
    from .poller import poll_device

    device = Device.objects.select_related("provider_account", "tenant").get(
        id=job.payload["device_id"]
    )
    if device.archived_at is not None:
        return {"skipped": "archived"}
    return poll_device(device, kind=job.payload.get("kind", "poll"))
