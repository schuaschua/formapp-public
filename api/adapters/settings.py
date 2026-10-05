"""The one settings object (coding-style.md rule 12, spine Consistency Conventions: Config).

Every setting comes from an environment variable; nothing else in the service reads the environment.
Loading fails with a message that names each bad variable and never prints its value (NFR17).
"""

import re
from pathlib import Path
from typing import Literal

from pydantic import (
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO = "demo"

# The api folder: alembic.ini and the migrations are bundled next to the code (AD-10).
API_ROOT = Path(__file__).resolve().parent.parent

# Demo must verify the server's certificate and host name, or the Entra token could be sent to an
# impostor (AD-10, NFR15).
DEMO_SSLMODE: Literal["verify-full"] = "verify-full"


# The parts of an Application Insights connection string the distro needs (Story 1.5).
_INSTRUMENTATION_KEY = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_ENDPOINT_KEYS = ("ingestionendpoint", "liveendpoint")


def _check_connection_string(value: str) -> None:
    """Raise ValueError (never quoting the value) unless it looks like a usable connection string."""
    parts: dict[str, str] = {}
    for part in value.split(";"):
        if not part.strip():
            continue
        key, separator, item = part.partition("=")
        if not separator or not key.strip():
            raise ValueError("expected Key=Value pairs separated by ';'")
        parts[key.strip().lower()] = item.strip()
    if not _INSTRUMENTATION_KEY.match(parts.get("instrumentationkey", "")):
        raise ValueError("InstrumentationKey must be a GUID")
    for key in _ENDPOINT_KEYS:
        if key in parts and not parts[key].startswith("https://"):
            raise ValueError("endpoints must be https:// URLs")


class SettingsError(RuntimeError):
    """Configuration is missing or invalid; the message names variables, never values."""


class Settings(BaseSettings):
    """Service configuration, read from environment variables of the same name in upper case."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    # "demo" is the deployed Azure environment; "local" covers developer machines and CI.
    formapp_deployment: Literal["demo", "local"]

    database_host: str = Field(min_length=1)
    database_name: str = Field(min_length=1)
    database_user: str = Field(min_length=1)
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_sslmode: Literal[
        "disable", "prefer", "require", "verify-ca", "verify-full"
    ] = DEMO_SSLMODE
    # CA roots for verify-ca/verify-full: a PEM bundle path, or "system" for libpq's default store.
    # The image sets the Debian bundle path: the OpenSSL bundled in the psycopg wheel doesn't
    # reliably find the system store on its own.
    database_sslrootcert: str = Field(default="system", min_length=1)
    # Local and CI databases only; demo signs in with an Entra token (AD-10).
    database_password: SecretStr | None = None
    # The AD-17 migration role, the same variable the deploy's migration step uses. Readiness fails
    # if it doesn't exist or api is a member of it.
    db_migration_role: str = Field(min_length=1)
    # Client ID of the api user-assigned managed identity, for the Entra database token.
    azure_client_id: str | None = None

    # AD-4 turn-token signing key, from the Container Apps secret the foundation stack sets.
    turn_token_signing_key: SecretStr = Field(min_length=32)

    # AD-18: lets a request carry a test principal (Story 1.6); refused in demo.
    formapp_test_mode: bool = False

    # The built web app (index.html and assets) served with SPA fallback.
    formapp_static_dir: Path = API_ROOT / "static"

    # Story 1.5: telemetry goes to Application Insights only when a connection string is set (the
    # foundation stack passes it as a Container Apps secret). Without it, telemetry is off.
    applicationinsights_connection_string: SecretStr | None = None
    # The lowest level logged to stdout (and so to ContainerAppConsoleLogs).
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # The share of traces kept, from 0 (none) to 1 (all) (azure.md rule 16).
    telemetry_sampling_ratio: float = Field(
        default=1.0, ge=0.0, le=1.0, allow_inf_nan=False
    )

    # Story 4.5: where `api` calls the hosted agent's Responses endpoint (AD-9). Already delivered
    # to the api container as plain env vars by infra/demo/agent/locals.tf's api_agent_env; unset
    # in test mode, where the AgentGateway stub is used instead (never a real Foundry call, AD-18).
    # `foundry_model` is also the model deployment name Story 4.9 logs on every answer_overrides
    # row (spine Consistency Conventions: "the model deployment name is config", AD-17); required
    # in demo already (see _guards below), so no separate placeholder default is needed there --
    # a local/CI run without it simply logs None, which the REST call site below turns into a
    # grep-able placeholder string before it reaches the domain layer.
    foundry_project_endpoint: str | None = None
    foundry_agent_name: str | None = None
    foundry_model: str | None = None

    # Story 6.1: where `api` mints browser Speech tokens (AD-19), for the dedicated speech identity
    # (never api's own). Already delivered to the api container as plain env vars by
    # infra/demo/foundation/locals.tf's api_env; unset in test/local, where the SpeechTokenIssuer
    # stub is used instead (never a real Azure call, AD-18); required together in demo (see
    # _guards below).
    speech_region: str | None = None
    speech_endpoint: str | None = None
    speech_resource_id: str | None = None
    speech_identity_client_id: str | None = None
    speech_locale: str | None = None
    speech_voice: str | None = None

    @field_validator("applicationinsights_connection_string", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # An empty variable means "not set", so a local run with it blank keeps telemetry off.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("applicationinsights_connection_string", mode="after")
    @classmethod
    def _usable_connection_string(cls, value: SecretStr | None) -> SecretStr | None:
        # Checked here so a malformed value stops startup naming the variable, before the distro
        # half-configures itself or prints its own error (Story 1.5).
        if value is not None:
            _check_connection_string(value.get_secret_value())
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _level_in_upper_case(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _guards(self) -> "Settings":
        if self.formapp_deployment == DEMO:
            if self.formapp_test_mode:
                raise ValueError(
                    "FORMAPP_TEST_MODE must not be on in the demo deployment (AD-18)"
                )
            if self.database_password is not None:
                raise ValueError(
                    "DATABASE_PASSWORD must not be set in the demo deployment; "
                    "it signs in with an Entra token (AD-10)"
                )
            if (
                self.applicationinsights_connection_string is not None
                and not self.azure_client_id
            ):
                raise ValueError(
                    "AZURE_CLIENT_ID is required when APPLICATIONINSIGHTS_CONNECTION_STRING is set "
                    "in the demo deployment: telemetry ingestion uses the managed identity "
                    "(local authentication is off)"
                )
            if self.database_sslmode != DEMO_SSLMODE:
                raise ValueError(
                    "DATABASE_SSLMODE must be verify-full in the demo deployment (AD-10)"
                )
            missing_foundry = [
                name
                for name, value in (
                    ("FOUNDRY_PROJECT_ENDPOINT", self.foundry_project_endpoint),
                    ("FOUNDRY_AGENT_NAME", self.foundry_agent_name),
                    ("FOUNDRY_MODEL", self.foundry_model),
                )
                if not value
            ]
            if missing_foundry:
                raise ValueError(
                    f"{', '.join(missing_foundry)} must be set in the demo deployment "
                    "(Story 4.5, AD-9): api calls the hosted agent through them"
                )
            missing_speech = [
                name
                for name, value in (
                    ("SPEECH_REGION", self.speech_region),
                    ("SPEECH_ENDPOINT", self.speech_endpoint),
                    ("SPEECH_RESOURCE_ID", self.speech_resource_id),
                    ("SPEECH_IDENTITY_CLIENT_ID", self.speech_identity_client_id),
                    ("SPEECH_LOCALE", self.speech_locale),
                    ("SPEECH_VOICE", self.speech_voice),
                )
                if not value
            ]
            if missing_speech:
                raise ValueError(
                    f"{', '.join(missing_speech)} must be set in the demo deployment "
                    "(Story 6.1, AD-19): api mints Speech tokens through them"
                )
        if self.database_password is None and not self.azure_client_id:
            raise ValueError(
                "AZURE_CLIENT_ID is required when DATABASE_PASSWORD is not set "
                "(Entra token sign-in with the managed identity)"
            )
        return self

    @property
    def is_demo(self) -> bool:
        return self.formapp_deployment == DEMO


def load_settings() -> Settings:
    """Build the settings from the environment, or raise SettingsError naming the bad variables."""
    try:
        return Settings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as exc:
        raise SettingsError(_describe(exc)) from None


def _describe(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors(
        include_input=False, include_url=False, include_context=False
    ):
        names = [str(part).upper() for part in error["loc"] if isinstance(part, str)]
        if error["type"] == "missing":
            problems.append(f"{names[0]} is required but not set")
        elif names:
            problems.append(f"{names[0]} is invalid: {error['msg']}")
        else:
            # Model-level guards write their own message, which names the setting.
            problems.append(str(error["msg"]).removeprefix("Value error, "))
    return "Invalid configuration: " + "; ".join(problems)
