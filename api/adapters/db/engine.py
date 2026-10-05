"""The PostgreSQL engine (spine AD-10).

In Azure, api signs in as its user-assigned managed identity with an Entra access token as the
password, over TLS. Tokens are cached and replaced before they expire; a password is accepted only
outside demo (local development and CI).
"""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import psycopg
from azure.identity import ManagedIdentityCredential
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from domain.clock import Clock

# Both adapters.settings.Settings and jobs.settings.JobSettings declare database_sslmode with this
# exact Literal (not plain str): a Protocol's instance attributes are matched invariantly, so
# DatabaseSettings below has to repeat it verbatim rather than widen it to str.
_SslMode = Literal["disable", "prefer", "require", "verify-ca", "verify-full"]

# Entra scope for Azure Database for PostgreSQL.
POSTGRES_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Get a new token when the cached one has less than this left, so a connection never starts with a
# token about to expire.
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

CONNECT_TIMEOUT_SECONDS = 5


class TokenCredential(Protocol):
    """The part of an azure-identity credential the engine uses."""

    def get_token(self, *scopes: str) -> Any: ...


class DatabaseSettings(Protocol):
    """The subset of settings the engine needs (Story 7.1/FORM-237): both
    ``adapters.settings.Settings`` (the api process) and ``jobs.settings.JobSettings`` (the
    nightly feedback job) satisfy this structurally, so this module serves both without either
    settings class depending on the other."""

    database_host: str
    database_port: int
    database_name: str
    database_user: str
    database_password: SecretStr | None
    database_sslmode: _SslMode
    database_sslrootcert: str
    azure_client_id: str | None


class EntraTokenProvider:
    """Caches the managed identity's database token and fetches a new one before it expires."""

    def __init__(self, credential: TokenCredential, clock: Clock) -> None:
        self._credential = credential
        self._clock = clock
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def password(self) -> str:
        async with self._lock:
            if not self._is_fresh():
                # azure-identity's credential is synchronous; keep its HTTP call off the event loop.
                access_token = await asyncio.to_thread(
                    self._credential.get_token, POSTGRES_ENTRA_SCOPE
                )
                if not access_token.token:
                    # Never cache or send an empty password.
                    raise RuntimeError("No database token was issued.")
                self._token = access_token.token
                self._expires_at = datetime.fromtimestamp(access_token.expires_on, UTC)
            return str(self._token)

    def _is_fresh(self) -> bool:
        if self._token is None or self._expires_at is None:
            return False
        return self._clock.now() + TOKEN_REFRESH_MARGIN < self._expires_at


# An async callable that returns the password for a new database connection.
PasswordSource = Callable[[], Coroutine[Any, Any, str]]


def build_password_source(settings: DatabaseSettings, clock: Clock) -> PasswordSource:
    """Return an async callable giving the connection password: the local one, or an Entra token."""
    if settings.database_password is not None:
        local_password = settings.database_password.get_secret_value()

        async def local() -> str:
            return local_password

        return local

    credential = ManagedIdentityCredential(client_id=settings.azure_client_id)
    return EntraTokenProvider(credential, clock).password


def connection_tls(settings: DatabaseSettings) -> dict[str, Any]:
    """libpq TLS parameters: verifying modes check the server against the configured CA roots."""
    tls: dict[str, Any] = {"sslmode": settings.database_sslmode}
    if settings.database_sslmode in ("verify-ca", "verify-full"):
        tls["sslrootcert"] = settings.database_sslrootcert
    return tls


def create_engine(
    settings: DatabaseSettings, password_source: PasswordSource
) -> AsyncEngine:
    """Create the async engine; each new pooled connection asks password_source for its password."""
    tls = connection_tls(settings)

    async def connect() -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            host=settings.database_host,
            port=settings.database_port,
            dbname=settings.database_name,
            user=settings.database_user,
            password=await password_source(),
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name="formapp-api",
            **tls,
        )

    return create_async_engine(
        "postgresql+psycopg://",
        async_creator=connect,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Connections outlive tokens safely (PostgreSQL checks the password only at sign-in), but
        # recycle them hourly anyway so a revoked identity is noticed.
        pool_recycle=3600,
    )
