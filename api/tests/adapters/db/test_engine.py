"""Story 1.3: PostgreSQL sign-in with the managed identity's Entra token over TLS (AD-10)."""

import asyncio
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from adapters.db import engine as engine_module
from adapters.db.engine import (
    POSTGRES_ENTRA_SCOPE,
    EntraTokenProvider,
    build_password_source,
    create_engine,
)
from tests.fakes import FakeAccessToken, FakeClock, FakeCredential
from tests.support import make_settings


def test_story_1_3_entra_token_is_cached_and_refreshed_before_expiry() -> None:
    clock = FakeClock()
    credential = FakeCredential(clock, lifetime=timedelta(hours=1))
    provider = EntraTokenProvider(credential, clock)

    first = asyncio.run(provider.password())
    clock.advance(timedelta(minutes=50))
    cached = asyncio.run(provider.password())
    # Less than five minutes left: a new token before the old one expires.
    clock.advance(timedelta(minutes=6))
    refreshed = asyncio.run(provider.password())

    assert first == cached == "synthetic-entra-token-1"
    assert refreshed == "synthetic-entra-token-2"
    assert credential.scopes == [(POSTGRES_ENTRA_SCOPE,), (POSTGRES_ENTRA_SCOPE,)]


@pytest.mark.parametrize("empty", [None, ""])
def test_story_1_3_entra_provider_rejects_an_empty_token(empty: str | None) -> None:
    clock = FakeClock()
    expires = int((clock.now() + timedelta(hours=1)).timestamp())

    class EmptyCredential:
        def __init__(self) -> None:
            self.calls = 0

        def get_token(self, *scopes: str) -> Any:
            self.calls += 1
            return FakeAccessToken(token=empty, expires_on=expires)  # type: ignore[arg-type]

    credential = EmptyCredential()
    provider = EntraTokenProvider(credential, clock)

    with pytest.raises(RuntimeError):
        asyncio.run(provider.password())
    # Not cached: the next connection asks the credential again.
    with pytest.raises(RuntimeError):
        asyncio.run(provider.password())
    assert credential.calls == 2


def test_story_1_3_managed_identity_is_used_without_a_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str | None] = []

    class RecordingCredential(FakeCredential):
        def __init__(self, client_id: str | None = None) -> None:
            created.append(client_id)
            super().__init__(FakeClock())

    monkeypatch.setattr(engine_module, "ManagedIdentityCredential", RecordingCredential)
    settings = make_settings(
        database_password=None, azure_client_id="00000000-aaaa-bbbb-cccc-000000000001"
    )

    source = build_password_source(settings, FakeClock())

    assert created == ["00000000-aaaa-bbbb-cccc-000000000001"]
    assert asyncio.run(source()) == "synthetic-entra-token-1"


def test_story_1_3_local_password_outside_demo() -> None:
    source = build_password_source(make_settings(), FakeClock())

    assert asyncio.run(source()) == "synthetic-api-password"


@pytest.mark.parametrize(
    ("sslmode", "sslrootcert", "configured_root"),
    [
        ("verify-full", "system", None),
        ("verify-ca", "system", None),
        ("require", None, None),
        (
            "verify-full",
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/ssl/certs/ca-certificates.crt",
        ),
    ],
)
def test_story_1_3_connection_uses_the_token_as_password_with_tls(
    monkeypatch: pytest.MonkeyPatch,
    sslmode: str,
    sslrootcert: str | None,
    configured_root: str | None,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_connect(**kwargs: Any) -> Any:
        captured.update(kwargs)
        raise OSError("synthetic: no network in unit tests")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", fake_connect)
    settings = make_settings(
        database_host="pgsql-synthetic.example.test",
        database_name="formapp",
        database_user="id-synthetic-api",
        database_sslmode=sslmode,
        **({"database_sslrootcert": configured_root} if configured_root else {}),
    )

    issued = "synthetic-entra-token"

    async def token() -> str:
        return issued

    async def try_connect() -> None:
        engine = create_engine(settings, token)
        try:
            async with engine.connect():
                pass
        finally:
            await engine.dispose()

    with pytest.raises(OSError):
        asyncio.run(try_connect())

    assert captured["password"] == issued
    assert captured["sslmode"] == sslmode
    # Verifying modes check the server against the configured roots (default: the system store).
    assert captured.get("sslrootcert") == sslrootcert
    assert captured["host"] == "pgsql-synthetic.example.test"
    assert captured["dbname"] == "formapp"
    assert captured["user"] == "id-synthetic-api"
