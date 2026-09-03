from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "apps.reports"
    label = "reports"
    verbose_name = "Raporty"

    def ready(self) -> None:
        from . import jobs  # noqa: F401 — registers render_report
