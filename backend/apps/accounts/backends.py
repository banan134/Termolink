"""Authentication backend aware of row-level security (docs/03, docs/08).

`authenticate()` looks a user up by e-mail before any tenant context exists, and
`get_user()` restores the session user at the start of a request; both run in the explicit
`system` context so RLS does not hide the row. Everything else stays isolated.
"""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.tenants.context import system_context

from .models import User


class RlsModelBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        with system_context():
            user = super().authenticate(request, username=username, password=password, **kwargs)
        return user

    def get_user(self, user_id: Any) -> User | None:
        with system_context():
            user = super().get_user(user_id)
        return user
