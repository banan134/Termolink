"""Settings entry point: picks the module by DJANGO_ENV (dev | prod)."""

import os

_env = os.environ.get("DJANGO_ENV", "dev")

if _env == "prod":
    from .prod import *  # noqa: F403
elif _env == "dev":
    from .dev import *  # noqa: F403
else:
    raise RuntimeError(f"Unknown DJANGO_ENV={_env!r}; expected 'dev' or 'prod'")
