from django.apps import AppConfig


class IngestConfig(AppConfig):
    name = "apps.ingest"
    label = "ingest"
    verbose_name = "Worker i kolejka zadań"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 — registers built-in job handlers
