"""Lays out a local PostgreSQL database like demo's and runs migrations, for the Playwright
checks' local api server (``scripts/check.sh e2e``) (Story 1.10, AD-11, AD-17, AD-18).

Not a test: a plain script, run once before the api server starts, reusing the same roles/database
helper `api/tests/support.py`'s fixtures use so the local stack matches demo's shape. The connection
comes from the same libpq environment variables scripts/check.sh sets for its PostgreSQL container
(PGHOST, PGPORT, PGUSER, PGPASSWORD as the server superuser; PGSSLMODE) -- see
``scripts/check.sh``'s ``api`` section for the same pattern.

Usage: ``uv run --no-sync python scripts/e2e_bootstrap.py <dbname>`` from ``api/``.
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

# So `tests.support` resolves regardless of the caller's own CWD (pytest gets this from its own
# `pythonpath` ini option; a plain script does not).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config

from adapters.rest.principal import TEST_PRINCIPALS
from migrations.session import migration_role, prepare_session
from tests.support import (
    API_ROOT,
    API_USER,
    DEPLOY_PASSWORD,
    DEPLOY_USER,
    MIGRATOR_ROLE,
    create_database,
)

# FORM-222: a fixed, recognisable synthetic name (never Ally Macbeal's own -- security.md rule 1)
# so web/e2e/schema-v1-compat.spec.ts can find this seeded v1 draft in the Drafts list by its own
# display name (`display_name`'s own "<First>_<Last>_Proposal_<NNN>" shape, domain/proposals.py)
# without needing to know its generated id.
_V1_DRAFT_FIRST_NAME = "Vera"
_V1_DRAFT_LAST_NAME = "Legacy"


def bootstrap(dbname: str) -> None:
    """Create ``dbname`` laid out like demo's (roles, ownership, grants) and run migrations."""
    create_database(dbname)
    os.environ["PGUSER"] = DEPLOY_USER
    os.environ["PGPASSWORD"] = DEPLOY_PASSWORD
    os.environ["PGDATABASE"] = dbname
    os.environ["DB_MIGRATION_ROLE"] = MIGRATOR_ROLE
    # Story 4.3 Part B, AD-17: migration 0009's row-level security policies are granted to this
    # role, the same one the local api server signs in as (create_database's own API_USER grants).
    os.environ["DB_API_PRINCIPAL"] = API_USER
    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    seed_v1_draft()


def seed_v1_draft() -> None:
    """FORM-222: one draft pinned to schema_version 1, owned by the "agent-a" test principal
    (AD-18), so an e2e test can prove an existing v1 draft still opens with 5 pages once v2.json
    is the latest version (`create_draft` always pins new drafts to `latest_version()`, so nothing
    reachable through the app itself can create one any more).

    Inserted directly (never through `domain.proposals.create_draft`/`SqlProposalStore`, which
    only ever write the latest version) using the same `SET ROLE`/session setup migrations
    themselves run under (`migrations.session.prepare_session`, PGUSER/PGPASSWORD/PGDATABASE
    already set by `bootstrap` above), so migration 0009's row-level security (AD-17) doesn't
    block it -- mirroring migration 0013's own data-seeding approach. Only C1/C13 are answered
    (enough for a recognisable `display_name`); AD-15's other defaults are this draft's own concern
    once opened, not this script's.
    """
    now = datetime.now(UTC).isoformat()
    answers = json.dumps(
        {
            "C1": {"value": _V1_DRAFT_FIRST_NAME, "source": "human", "updated_at": now},
            "C13": {"value": _V1_DRAFT_LAST_NAME, "source": "human", "updated_at": now},
        }
    )
    owner_oid = TEST_PRINCIPALS["agent-a"].oid
    with psycopg.connect() as connection:
        prepare_session(connection, migration_role())
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO proposal
                (owner_oid, owner_seq, schema_version, status, revision, answers,
                 created_at, updated_at)
            VALUES (
                %(owner_oid)s,
                COALESCE(
                    (SELECT MAX(owner_seq) FROM proposal WHERE owner_oid = %(owner_oid)s), 0
                ) + 1,
                1, 'draft', 0, %(answers)s::jsonb, now(), now()
            )
            """,
            {"owner_oid": owner_oid, "answers": answers},
        )
        connection.commit()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: e2e_bootstrap.py <dbname>", file=sys.stderr)
        raise SystemExit(2)
    bootstrap(sys.argv[1])
    print(f"Bootstrapped {sys.argv[1]} for the local Playwright stack.")


if __name__ == "__main__":
    main()
