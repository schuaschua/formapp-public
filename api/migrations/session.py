"""Session setup for migration connections (spine AD-10, AD-17).

Kept out of env.py so tests can import it: env.py runs migrations as soon as Alembic loads it.
"""

from typing import Any

from pydantic_settings import BaseSettings

# The old api keeps serving while migrations run: wait at most this long for a lock, and stop any
# statement that runs longer, instead of stalling api's requests behind a migration.
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "60s"


class MigrationSettings(BaseSettings):
    """The migration step's own settings; libpq reads the PG* variables itself."""

    db_migration_role: str | None = None
    # [ASSUMPTION] (Story 4.3 Part B): the running api's own database role/managed identity name,
    # named here so migration 0009's row-level security policies can grant it `TO <this role>`.
    # Deploy env: `id-sample-demo-sea-api` (infra/bootstrap/README.md); tests: the existing test
    # role `tests.support.API_USER`.
    db_api_principal: str | None = None


def migration_role() -> str:
    """The role migrations run as; refuse to migrate without one (AD-17)."""
    role = (MigrationSettings().db_migration_role or "").strip()
    if not role:
        raise RuntimeError(
            "DB_MIGRATION_ROLE is not set; refusing to migrate, because every object must be "
            "owned by the migration role (AD-17)."
        )
    return role


def api_principal() -> str:
    """The role the api-scoped row-level security policies are granted to; refuse to migrate
    without one (Story 4.3 Part B, AD-17, security.md rule 37)."""
    role = (MigrationSettings().db_api_principal or "").strip()
    if not role:
        raise RuntimeError(
            "DB_API_PRINCIPAL is not set; refusing to migrate, because the per-proposal and "
            "per-owner row-level security policies must be granted to the api role by name (AD-17)."
        )
    return role


def prepare_session(dbapi_connection: Any, role: str) -> None:
    """SET ROLE and the timeouts on a new connection; set_config binds every value."""
    with dbapi_connection.cursor() as cursor:
        for name, value in (
            ("role", role),
            ("lock_timeout", LOCK_TIMEOUT),
            ("statement_timeout", STATEMENT_TIMEOUT),
        ):
            cursor.execute("SELECT set_config(%s, %s, false)", (name, value))
    # Session-level (is_local false), so the settings outlive this transaction.
    dbapi_connection.commit()
