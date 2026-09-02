from typing import Any

from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "apps.tenants"
    label = "tenants"
    verbose_name = "Klienci"

    def ready(self) -> None:
        from django.contrib.auth.models import update_last_login
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        from .context import ANONYMOUS, context_for_user, set_context, system_context

        # Django's receiver would UPDATE users before the RLS context knows who logged in.
        user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")

        def on_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
            with system_context():
                ctx = context_for_user(user)
            set_context(ctx)
            if request is not None:
                request.tenant_context = ctx
            update_last_login(sender, user)

        def on_logout(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
            set_context(ANONYMOUS)
            if request is not None:
                request.tenant_context = ANONYMOUS

        user_logged_in.connect(on_login, dispatch_uid="tenants.on_login", weak=False)
        user_logged_out.connect(on_logout, dispatch_uid="tenants.on_logout", weak=False)
