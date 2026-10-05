"""Alembic environment (spine AD-10, AD-11, AD-17).

Run only by the deploy pipeline's migration step, never by api at startup. The connection comes
entirely from the libpq environment variables that step exports (PGHOST, PGUSER, PGPASSWORD holding
an Entra token, PGDATABASE, PGSSLMODE). Every connection first runs SET ROLE to DB_MIGRATION_ROLE,
so the migration role owns every object the migrations create (AD-17), and sets lock and statement
timeouts.
"""

from typing import Any

from alembic import context
from sqlalchemy import create_engine, event, pool, text

from migrations.session import migration_role, prepare_session


def run_migrations_online() -> None:
    role = migration_role()
    # An empty URL: psycopg hands libpq an empty conninfo, and libpq reads the PG* variables.
    engine = create_engine("postgresql+psycopg://", poolclass=pool.NullPool)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        prepare_session(dbapi_connection, role)

    with engine.connect() as connection:
        current = connection.execute(text("SELECT current_user")).scalar_one()
        if current != role:
            raise RuntimeError(
                f"SET ROLE {role} did not take effect; refusing to migrate."
            )
        # End the check's implicit transaction so Alembic's own transactions commit.
        connection.commit()
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline (--sql) migrations are not used; run them online from the pipeline."
    )
run_migrations_online()
