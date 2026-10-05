"""Story 4.3 Part B / Story 4.9 / Story 4.8 P0: the shape of row-level security itself, on
``proposal`` (migration 0009), ``answer_overrides`` (migration 0012) and ``chat_turn_log``
(migration 0017) alike (spine AD-17, security.md rule 37) -- independent of any one query or
update, in case a future migration weakens it without anyone noticing at the query level.

``proposal_feedback`` (migration 0019, Story 7.2/FORM-238) is RLS-enabled here too, but with a
*different* policy shape -- an insert policy, a delete policy and a job-scope policy, not AD-17's
owner_oid/proposal_id pair -- since it exists for one job's deliberate, least-privilege cross-owner
need, not AD-17's per-request scoping (see that migration's own docstring). Migration 0020
(Story 7.3/FORM-239) adds one more job-scope policy to ``proposal`` itself, for the same reason and
narrowed further to submitted proposals only."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from tests.support import API_USER, MIGRATOR_ROLE

pytestmark = pytest.mark.p0

Admin = Callable[[str], psycopg.Connection[Any]]

# Table name -> its policy names and the roles each is granted TO. Every table under AD-17 has the
# same three-policy shape (migrator/proposal_id/owner_oid), just renamed per table, so these tests
# are written once, parametrized over this dict, rather than duplicated per table.
_EXPECTED_POLICIES: dict[str, dict[str, frozenset[str]]] = {
    # Story 7.3/FORM-239, migration 0020 adds a fourth, job-scope, submitted-only SELECT policy
    # (the nightly export's own narrow read path) alongside AD-17's own three.
    "proposal": {
        "proposal_migrator_all": frozenset({MIGRATOR_ROLE}),
        "proposal_api_by_proposal_id": frozenset({API_USER}),
        "proposal_api_by_owner_oid": frozenset({API_USER}),
        "proposal_api_job_scope_select_submitted": frozenset({API_USER}),
    },
    "answer_overrides": {
        "answer_overrides_migrator_all": frozenset({MIGRATOR_ROLE}),
        "answer_overrides_api_by_proposal_id": frozenset({API_USER}),
        "answer_overrides_api_by_owner_oid": frozenset({API_USER}),
    },
    # Story 4.8: the _api_by_owner_oid-only shape (no MCP tool ever touches this table, so no
    # proposal_id policy) -- spec Boundaries.
    "chat_turn_log": {
        "chat_turn_log_migrator_all": frozenset({MIGRATOR_ROLE}),
        "chat_turn_log_api_by_owner_oid": frozenset({API_USER}),
    },
    # Story 7.2/FORM-238, migration 0019: not AD-17's owner_oid/proposal_id shape -- an
    # unconditional insert policy (preserving today's REST-submit behaviour unchanged) plus two
    # job-scope policies (the new, deliberate cross-owner path; PostgreSQL requires a SELECT policy
    # alongside the UPDATE one so the job can find the rows it updates).
    "proposal_feedback": {
        "proposal_feedback_migrator_all": frozenset({MIGRATOR_ROLE}),
        "proposal_feedback_api_insert": frozenset({API_USER}),
        "proposal_feedback_api_job_scope_select": frozenset({API_USER}),
        "proposal_feedback_api_job_scope_update": frozenset({API_USER}),
    },
}


@pytest.mark.parametrize("table", sorted(_EXPECTED_POLICIES))
def test_p0_row_level_security_is_enabled_and_forced(
    admin: Admin, migrated_db: str, table: str
) -> None:
    with admin(migrated_db) as connection:
        enabled, forced = connection.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = %s AND relnamespace = 'public'::regnamespace",
            (table,),
        ).fetchone()
    assert (enabled, forced) == (True, True)


@pytest.mark.parametrize("table", sorted(_EXPECTED_POLICIES))
def test_p0_formapp_migrator_owns_the_table(
    admin: Admin, migrated_db: str, table: str
) -> None:
    with admin(migrated_db) as connection:
        owner = connection.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = %s",
            (table,),
        ).fetchone()
    assert owner is not None
    assert owner[0] == MIGRATOR_ROLE


@pytest.mark.parametrize("table", sorted(_EXPECTED_POLICIES))
def test_p0_every_policy_is_permissive_and_never_to_public(
    admin: Admin, migrated_db: str, table: str
) -> None:
    with admin(migrated_db) as connection:
        rows = connection.execute(
            "SELECT policyname, permissive, roles FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename = %s",
            (table,),
        ).fetchall()
    policies = {
        name: (permissive, frozenset(roles)) for name, permissive, roles in rows
    }
    expected = _EXPECTED_POLICIES[table]

    assert set(policies) == set(expected)
    for name, (permissive, roles) in policies.items():
        assert permissive == "PERMISSIVE", f"{name} is not permissive"
        assert "public" not in {role.lower() for role in roles}, f"{name} is TO PUBLIC"
        assert roles == expected[name], f"{name} has unexpected roles {roles}"


def test_p0_any_view_over_proposal_is_security_invoker(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        views = connection.execute(
            "SELECT c.relname, "
            "coalesce((SELECT option_value = 'true' FROM pg_options_to_table(c.reloptions) "
            "WHERE option_name = 'security_invoker'), false) AS security_invoker "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'v' AND n.nspname = 'public' "
            "AND pg_get_viewdef(c.oid) ILIKE '%proposal%'"
        ).fetchall()
    for name, security_invoker in views:
        assert security_invoker, f"view {name} over proposal is not security_invoker"


def test_p0_api_is_not_a_member_of_formapp_migrator(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        is_member = connection.execute(
            "SELECT pg_has_role(%s, %s, 'MEMBER')", (API_USER, MIGRATOR_ROLE)
        ).fetchone()
    assert is_member is not None
    assert is_member[0] is False


def test_p0_api_has_only_select_and_insert_on_answer_overrides(
    admin: Admin, migrated_db: str
) -> None:
    """Story 4.9, AC1/security.md rule 31: migration 0012 narrows the api role's grant down from
    the bootstrap's default SELECT/INSERT/UPDATE/DELETE (append-only for that role). Migration 0016
    (Story FORM-227) grants DELETE back -- never UPDATE -- gated by the table's own guard trigger
    instead of the grant system (see test_rls.py's ``test_p0_api_cannot_update_or_delete_answer_
    overrides``)."""
    with admin(migrated_db) as connection:
        privileges = connection.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = 'answer_overrides' AND grantee = %s",
            (API_USER,),
        ).fetchall()
    assert {row[0] for row in privileges} == {"SELECT", "INSERT", "DELETE"}


def test_p0_api_has_only_select_and_insert_on_chat_turn_log(
    admin: Admin, migrated_db: str
) -> None:
    """Story 4.8, migration 0017 (security.md rule 31): the throttle check only ever reads the
    rolling window and inserts one row -- never updates or deletes one."""
    with admin(migrated_db) as connection:
        privileges = connection.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = 'chat_turn_log' AND grantee = %s",
            (API_USER,),
        ).fetchall()
    assert {row[0] for row in privileges} == {"SELECT", "INSERT"}


def test_p0_api_has_select_insert_and_update_on_proposal_feedback(
    admin: Admin, migrated_db: str
) -> None:
    """Story 7.2/FORM-238, migration 0019 (security.md rule 31): unlike ``answer_overrides`` and
    ``chat_turn_log``, this table's UPDATE grant is genuine (the job writes ``category`` here) --
    the job-scope policy, not the grant system, is what keeps SELECT/UPDATE to the job alone
    (``test_rls_feedback.py``). No DELETE: the cascade-on-submitted-delete path it would serve is
    unreachable (submitted proposals can never be deleted, ``test_proposals.py``'s own
    ``test_form_227_delete_rejects_a_submitted_proposal``)."""
    with admin(migrated_db) as connection:
        privileges = connection.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = 'proposal_feedback' AND grantee = %s",
            (API_USER,),
        ).fetchall()
    assert {row[0] for row in privileges} == {"SELECT", "INSERT", "UPDATE"}
