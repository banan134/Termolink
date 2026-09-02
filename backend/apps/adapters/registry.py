"""Adapter registry (docs/05): provider_accounts.provider must be a key here."""

from .base import ProviderAdapter

ADAPTERS: dict[str, ProviderAdapter] = {}


def register(adapter: ProviderAdapter) -> ProviderAdapter:
    if adapter.id in ADAPTERS:
        raise RuntimeError(f"adapter {adapter.id!r} already registered")
    ADAPTERS[adapter.id] = adapter
    return adapter


def get_adapter(provider: str) -> ProviderAdapter:
    try:
        return ADAPTERS[provider]
    except KeyError as exc:
        raise KeyError(f"unknown provider {provider!r}; registered: {sorted(ADAPTERS)}") from exc


def _load_builtin() -> None:
    """Real adapter, or the fixture-backed mock when VIESSMANN_MOCK=1 (docs/15)."""
    from django.conf import settings

    if "viessmann" in ADAPTERS:
        return
    if getattr(settings, "VIESSMANN_MOCK", False):
        from .viessmann.mock import MockViessmannAdapter

        register(MockViessmannAdapter())
    else:
        from .viessmann.adapter import ViessmannAdapter

        register(ViessmannAdapter())


def reset_for_tests() -> None:
    ADAPTERS.clear()
    _load_builtin()


_load_builtin()
