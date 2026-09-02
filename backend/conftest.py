"""Root pytest config: isolate DRF throttle counters (locmem cache) between tests."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()
