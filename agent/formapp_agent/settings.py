"""The one settings object (coding-style.md rule 12, spine Consistency Conventions: Config).

Every setting comes from an environment variable; nothing else in the agent reads the environment.
Loading fails with a message that names each bad variable and never prints its value (NFR17).
The model deployment name reaches the code only as ``MODEL_DEPLOYMENT_NAME`` (NFR23): the platform
reserves ``FOUNDRY_*``/``AGENT_*`` names for itself and rejects a hosted-agent version that declares
one (Microsoft Learn, "Deploy a hosted agent" and "Configure environment variables for a hosted
agent").
"""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The parts of an Application Insights connection string the exporter needs (as in api/, Story 1.5).
_INSTRUMENTATION_KEY = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_ENDPOINT_KEYS = ("ingestionendpoint", "liveendpoint")
# Plain HTTP is allowed only to this machine (a local api during a live evaluation run); the turn
# token must never cross a network unencrypted (AD-4).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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


def _check_url(value: str, *, allow_loopback_http: bool) -> str:
    """Raise ValueError (never quoting the value) unless ``value`` is an absolute https URL."""
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError("must be an absolute URL") from None
    if not parts.scheme or not parts.hostname:
        raise ValueError("must be an absolute URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not carry credentials")
    if parts.scheme == "https":
        return value
    if (
        allow_loopback_http
        and parts.scheme == "http"
        and parts.hostname in _LOOPBACK_HOSTS
    ):
        return value
    raise ValueError("must be an https:// URL")


class SettingsError(RuntimeError):
    """Configuration is missing or invalid; the message names variables, never values."""


class Settings(BaseSettings):
    """Agent configuration, read from environment variables of the same name in upper case."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    # The api MCP endpoint (AD-1, AD-3): the agent's only tool source.
    formapp_mcp_url: str = Field(min_length=1)
    # The Foundry project the model deployment lives in. The platform injects this itself in the
    # hosted container (it is never in the hosted agent's declared environment_variables); locally
    # and in CI it is set like any other variable.
    foundry_project_endpoint: str = Field(min_length=1)
    # The model deployment name (NFR23); never written in code. Named MODEL_DEPLOYMENT_NAME, not
    # FOUNDRY_MODEL, because FOUNDRY_* is reserved for the platform.
    model_deployment_name: str = Field(min_length=1)

    # Telemetry goes to Application Insights only when a connection string is set; without it
    # nothing is exported.
    applicationinsights_connection_string: SecretStr | None = None
    # Client ID of a user-assigned managed identity for Foundry and telemetry ingestion; without it
    # the default Azure credential chain is used.
    azure_client_id: str | None = None
    # The share of new traces kept, from 0 (none) to 1 (all); a turn that arrives with a sampled
    # traceparent is always kept, so one chat turn stays one trace (azure.md rule 16).
    telemetry_sampling_ratio: float = Field(
        default=1.0, ge=0.0, le=1.0, allow_inf_nan=False
    )
    # The lowest level logged to stdout.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("formapp_mcp_url", mode="after")
    @classmethod
    def _mcp_url(cls, value: str) -> str:
        return _check_url(value, allow_loopback_http=True)

    @field_validator("foundry_project_endpoint", mode="after")
    @classmethod
    def _project_endpoint(cls, value: str) -> str:
        return _check_url(value, allow_loopback_http=False)

    @field_validator("model_deployment_name", mode="after")
    @classmethod
    def _model_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator(
        "applicationinsights_connection_string", "azure_client_id", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # An empty variable means "not set", so a local run with it blank keeps telemetry off.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("applicationinsights_connection_string", mode="after")
    @classmethod
    def _usable_connection_string(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            _check_connection_string(value.get_secret_value())
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _level_in_upper_case(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


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
        else:
            problems.append(f"{names[0]} is invalid: {error['msg']}")
    return "Invalid configuration: " + "; ".join(problems)
