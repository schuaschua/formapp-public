"""Readiness against the database (spine AD-10, AD-17).

api is ready only when PostgreSQL is reachable, its Alembic revision equals the head bundled in this
image (so the app never serves traffic against the wrong schema), and the signed-in user is not a
member of the migration role (AD-17: api is never granted it). Migrations never run here.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.settings import API_ROOT

logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 4.0

# Whether the migration role exists, and whether the signed-in user is a member of it.
_MIGRATOR_MEMBERSHIP = text(
    "SELECT count(*) > 0, "
    "coalesce(bool_or(pg_has_role(current_user, r.oid, 'MEMBER')), false) "
    "FROM pg_roles AS r WHERE r.rolname = :role"
)
# alembic_version doesn't exist until the pipeline's first migration run.
_ALEMBIC_TABLE_EXISTS = text("SELECT to_regclass('alembic_version') IS NOT NULL")
_ALEMBIC_REVISIONS = text("SELECT version_num FROM alembic_version")


class NotReady(StrEnum):
    DATABASE_UNREACHABLE = "database_unreachable"
    DATABASE_ERROR = "database_error"
    MIGRATION_ROLE_MISSING = "migration_role_missing"
    SCHEMA_REVISION_MISMATCH = "schema_revision_mismatch"
    MIGRATION_ROLE_MEMBER = "migration_role_member"


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    reason: NotReady | None = None


def bundled_head(alembic_ini: str | None = None) -> str:
    """Return the single Alembic head revision shipped with this image."""
    config = Config(alembic_ini or str(API_ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head, found {len(heads)}.")
    return heads[0]


def _sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE of a database error, if the server sent one."""
    original = getattr(exc, "orig", exc)
    return (
        getattr(original, "sqlstate", None)
        if isinstance(original, psycopg.Error)
        else None
    )


async def check_readiness(
    engine: AsyncEngine, expected_head: str, migration_role: str
) -> Readiness:
    """Check the database; never raises, and logs why it isn't ready without connection details."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            role_exists, is_migrator, revisions = await _read_state(
                engine, migration_role
            )
    # Readiness answers 503, never 500, whatever fails.
    except Exception as exc:  # noqa: BLE001
        # The exception text can include the host, user or SQL, so only its type and SQLSTATE
        # are logged.
        sqlstate = _sqlstate(exc)
        if sqlstate and not sqlstate.startswith("08"):
            # The server answered with an error (permissions, missing object, sign-in rejected).
            logger.error(
                "Not ready: database error (%s, SQLSTATE %s).",
                type(exc).__name__,
                sqlstate,
            )
            return Readiness(ready=False, reason=NotReady.DATABASE_ERROR)
        logger.warning("Not ready: database unreachable (%s).", type(exc).__name__)
        return Readiness(ready=False, reason=NotReady.DATABASE_UNREACHABLE)

    if not role_exists:
        logger.error(
            "Not ready: the migration role %s does not exist, so AD-17 can't be checked.",
            migration_role,
        )
        return Readiness(ready=False, reason=NotReady.MIGRATION_ROLE_MISSING)
    if is_migrator:
        logger.error(
            "Not ready: AD-17 violation, the api database user is a member of the migration role %s.",
            migration_role,
        )
        return Readiness(ready=False, reason=NotReady.MIGRATION_ROLE_MEMBER)
    if revisions != [expected_head]:
        logger.warning(
            "Not ready: database schema revision %s does not match the bundled head %s.",
            ",".join(revisions) or "none",
            expected_head,
        )
        return Readiness(ready=False, reason=NotReady.SCHEMA_REVISION_MISMATCH)
    return Readiness(ready=True)


async def _read_state(
    engine: AsyncEngine, migration_role: str
) -> tuple[bool, bool, list[str]]:
    async with engine.connect() as connection:
        membership = await connection.execute(
            _MIGRATOR_MEMBERSHIP, {"role": migration_role}
        )
        role_exists, is_migrator = membership.one()
        revisions: list[str] = []
        if (await connection.execute(_ALEMBIC_TABLE_EXISTS)).scalar_one():
            revisions = list((await connection.execute(_ALEMBIC_REVISIONS)).scalars())
    return bool(role_exists), bool(is_migrator), sorted(revisions)
