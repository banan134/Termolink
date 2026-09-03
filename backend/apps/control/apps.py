from django.apps import AppConfig


class ControlConfig(AppConfig):
    name = "apps.control"
    label = "control"
    verbose_name = "Sterowanie"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 — registers execute_command / verify_command
