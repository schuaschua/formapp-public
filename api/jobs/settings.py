"""The nightly feedback job's own settings (Story 7.1/FORM-237, coding-style.md rule 12, spine
AD-20).

Kept separate from ``adapters.settings.Settings``: that class's demo guards require things only the
request-serving api process uses (the turn-token signing key, Speech settings), which this batch job
never touches. Both classes read the same ``DATABASE_*``/``FOUNDRY_*``/``AZURE_CLIENT_ID`` variable
names ``infra/demo/foundation`` already sets for ``api``, plus this job's own
``FEEDBACK_EXPORT_*`` names. Loading fails with a message that names each bad variable and never
prints its value (NFR17, mirroring ``adapters.settings.load_settings``).
"""

from typing import Literal

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO = "demo"

# Demo must verify the server's certificate and host name, or the Entra token could be sent to an
# impostor (AD-10, NFR15) -- same rule adapters.settings.Settings enforces for api.
DEMO_SSLMODE: Literal["verify-full"] = "verify-full"


class JobSettingsError(RuntimeError):
    """Configuration is missing or invalid; the message names variables, never values."""


class JobSettings(BaseSettings):
    """The feedback job's configuration, read from environment variables of the same name in
    upper case."""

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
    database_sslrootcert: str = Field(default="system", min_length=1)
    # Local and CI databases only; demo signs in with an Entra token (AD-10).
    database_password: SecretStr | None = None
    # Client ID of the api user-assigned managed identity, for the Entra database token: the job
    # runs as this same identity (AD-20).
    azure_client_id: str | None = None

    # Story 7.2: the Foundry model call (Responses API, no tools, temperature 0, AD-20). Set
    # directly by `infra/demo/foundation` -- unlike api's own copies of these three, the job has no
    # second Terraform stack patching its env, so it needs no dependency on `infra/demo/agent`.
    foundry_project_endpoint: str | None = None
    foundry_agent_name: str | None = None
    foundry_model: str | None = None

    # Story 7.3: the private feedback-export container and its anonymising salt (AD-20).
    feedback_export_container_url: str | None = None
    feedback_export_salt: SecretStr | None = None

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @model_validator(mode="after")
    def _guards(self) -> "JobSettings":
        if self.formapp_deployment == DEMO:
            if self.database_password is not None:
                raise ValueError(
                    "DATABASE_PASSWORD must not be set in the demo deployment; "
                    "it signs in with an Entra token (AD-10)"
                )
            if self.database_sslmode != DEMO_SSLMODE:
                raise ValueError(
                    "DATABASE_SSLMODE must be verify-full in the demo deployment (AD-10)"
                )
            missing = [
                name
                for name, value in (
                    ("FOUNDRY_PROJECT_ENDPOINT", self.foundry_project_endpoint),
                    ("FOUNDRY_AGENT_NAME", self.foundry_agent_name),
                    ("FOUNDRY_MODEL", self.foundry_model),
                    (
                        "FEEDBACK_EXPORT_CONTAINER_URL",
                        self.feedback_export_container_url,
                    ),
                    ("FEEDBACK_EXPORT_SALT", self.feedback_export_salt),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} must be set in the demo deployment (Story 7.1, AD-20)"
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


def load_job_settings() -> JobSettings:
    """Build the job's settings from the environment, or raise JobSettingsError naming the bad
    variables."""
    try:
        return JobSettings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as exc:
        raise JobSettingsError(_describe(exc)) from None


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
