"""Row-level security policies for tables carrying `tenant_id` (docs/03).

Usage in a migration:

    operations = [*rls_operations("devices"), *rls_operations("users", tenant_nullable=True)]
"""

import re

from django.db import migrations

_TABLE = re.compile(r"^[a-z_][a-z0-9_]*$")

_TENANT_ID = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_ALLOWED = "string_to_array(NULLIF(current_setting('app.allowed_tenants', true), ''), ',')::uuid[]"
_ROLE = "current_setting('app.role', true)"


def rls_operations(table: str, *, tenant_nullable: bool = False) -> list[migrations.RunSQL]:
    if not _TABLE.match(table):
        raise ValueError(f"invalid table name: {table!r}")
    policies = [
        (
            "tenant_isolation",
            f"USING (tenant_id = {_TENANT_ID}) WITH CHECK (tenant_id = {_TENANT_ID})",
        ),
        (
            "operator_access",
            f"USING ({_ROLE} = 'operator' AND tenant_id = ANY ({_ALLOWED}))",
        ),
        ("system_access", f"USING ({_ROLE} = 'system')"),
    ]
    if tenant_nullable:
        policies.append(
            ("operator_global_rows", f"USING ({_ROLE} = 'operator' AND tenant_id IS NULL)")
        )

    forward = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        *(f"CREATE POLICY {name} ON {table} {body};" for name, body in policies),
    ]
    backward = [
        *(f"DROP POLICY IF EXISTS {name} ON {table};" for name, _ in policies),
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
    ]
    return [migrations.RunSQL(sql="\n".join(forward), reverse_sql="\n".join(backward))]


# Registry of protected tables (checked by tests against pg_policies). Each new table gets its
# own migration calling rls_operations(); migrations must not iterate this dict.
RLS_TABLES: dict[str, bool] = {
    # table: tenant_id nullable
    "users": True,
    "invitations": True,
    "tenant_memberships": False,
    "user_sessions": True,
    "audit_log": True,
}
