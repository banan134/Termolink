"""RLS on provider_accounts and oauth_states (docs/03)."""

from django.db import migrations

from apps.tenants.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [
        ("providers", "0001_initial"),
        ("tenants", "0004_rls_user_sessions"),
    ]

    operations = [*rls_operations("provider_accounts"), *rls_operations("oauth_states")]
