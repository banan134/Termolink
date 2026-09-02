"""Runtime DB role management (docs/03 §Izolacja).

`ensure_app_role()` is idempotent and safe to run on every start: it creates or updates the
`DB_APP_USER` role (LOGIN, NOBYPASSRLS, password from `DB_APP_PASSWORD`) and (re)grants DML on
all current tables plus default privileges for future ones. Must run as the owner role.
"""

from typing import Any

from django.conf import settings
from psycopg import sql

_GRANTS = (
    "GRANT USAGE ON SCHEMA public TO {role}",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}",
)


def ensure_app_role(cursor: Any, raw_connection: Any) -> bool:
    """Create or update the app role. Returns True if the role was newly created."""
    user: str = settings.DB_APP_USER
    password: str = settings.DB_APP_PASSWORD
    if not password:
        raise RuntimeError("DB_APP_PASSWORD must be set (deploy/.env) to create the app DB role")
    ident = sql.Identifier(user)

    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [user])
    exists = cursor.fetchone() is not None
    verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
    cursor.execute(
        sql.SQL("{verb} {role} WITH LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB PASSWORD {pwd}")
        .format(verb=verb, role=ident, pwd=sql.Literal(password))
        .as_string(raw_connection)
    )
    for statement in _GRANTS:
        cursor.execute(sql.SQL(statement).format(role=ident).as_string(raw_connection))
    return not exists
