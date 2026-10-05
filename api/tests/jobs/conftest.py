"""Shared fixtures for `jobs.feedback` tests (Story 7.1/FORM-237, Story 7.2/FORM-238, Story
7.3/FORM-239)."""

import os

import pytest

from tests.support import API_PASSWORD, API_USER


@pytest.fixture
def job_env(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> pytest.MonkeyPatch:
    """A local (never demo) job configuration signed in as the test api role, on migrated_db. The
    export salt is set here too (Story 7.3): harmless for Story 7.2's own tests (nothing reads it
    unless a test passes a `snapshot_export_port`), and every export test needs a known, fixed
    value to assert `agent_hash`/`proposal_hash` are deterministic."""
    monkeypatch.setenv("FORMAPP_DEPLOYMENT", "local")
    monkeypatch.setenv("DATABASE_HOST", os.environ["PGHOST"])
    monkeypatch.setenv("DATABASE_PORT", os.environ.get("PGPORT", "5432"))
    monkeypatch.setenv("DATABASE_NAME", migrated_db)
    monkeypatch.setenv("DATABASE_USER", API_USER)
    monkeypatch.setenv("DATABASE_PASSWORD", API_PASSWORD)
    monkeypatch.setenv("DATABASE_SSLMODE", "disable")
    monkeypatch.setenv("FEEDBACK_EXPORT_SALT", "synthetic-export-salt")
    return monkeypatch
