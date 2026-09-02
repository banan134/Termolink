from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    name = "apps.providers"
    label = "providers"
    verbose_name = "Konta producentów"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 — registers the `discover` job handler
