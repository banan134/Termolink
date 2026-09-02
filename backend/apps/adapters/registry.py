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
    from .viessmann.adapter import ViessmannAdapter

    if "viessmann" not in ADAPTERS:
        register(ViessmannAdapter())


_load_builtin()
