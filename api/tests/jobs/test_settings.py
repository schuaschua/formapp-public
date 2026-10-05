"""Story 7.1/FORM-237: the feedback job's own settings, separate from api's (AD-20)."""

import pytest

from jobs.settings import JobSettingsError, load_job_settings

# Distinctive synthetic values, so a test can prove none of them is ever printed.
DEMO_ENV = {
    "FORMAPP_DEPLOYMENT": "demo",
    "DATABASE_HOST": "pgsql-synthetic-host.example.test",
    "DATABASE_NAME": "formapp",
    "DATABASE_USER": "id-synthetic-api",
    "AZURE_CLIENT_ID": "00000000-1111-2222-3333-444444444444",
    "FOUNDRY_PROJECT_ENDPOINT": "https://synthetic-foundry.example.test/api/projects/formapp",
    "FOUNDRY_AGENT_NAME": "formapp-agent",
    "FOUNDRY_MODEL": "synthetic-model-deployment",
    "FEEDBACK_EXPORT_CONTAINER_URL": (
        "https://stsamplefbdemosea.blob.core.windows.net/feedback-export"
    ),
    "FEEDBACK_EXPORT_SALT": "synthetic-salt-must-not-print",
}
SETTING_NAMES = [
    "FORMAPP_DEPLOYMENT",
    "DATABASE_HOST",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PORT",
    "DATABASE_SSLMODE",
    "DATABASE_PASSWORD",
    "AZURE_CLIENT_ID",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_AGENT_NAME",
    "FOUNDRY_MODEL",
    "FEEDBACK_EXPORT_CONTAINER_URL",
    "FEEDBACK_EXPORT_SALT",
    "LOG_LEVEL",
]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A clean environment holding exactly the demo settings."""
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in DEMO_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _load_error() -> str:
    with pytest.raises(JobSettingsError) as caught:
        load_job_settings()
    return str(caught.value)


def test_form_237_settings_come_from_environment_variables(
    env: pytest.MonkeyPatch,
) -> None:
    settings = load_job_settings()

    assert settings.is_demo
    assert settings.database_host == DEMO_ENV["DATABASE_HOST"]
    assert settings.database_user == DEMO_ENV["DATABASE_USER"]
    assert settings.database_sslmode == "verify-full"
    assert settings.foundry_project_endpoint == DEMO_ENV["FOUNDRY_PROJECT_ENDPOINT"]
    assert settings.foundry_agent_name == DEMO_ENV["FOUNDRY_AGENT_NAME"]
    assert settings.foundry_model == DEMO_ENV["FOUNDRY_MODEL"]
    assert (
        settings.feedback_export_container_url
        == DEMO_ENV["FEEDBACK_EXPORT_CONTAINER_URL"]
    )
    assert (
        settings.feedback_export_salt is not None
        and settings.feedback_export_salt.get_secret_value()
        == DEMO_ENV["FEEDBACK_EXPORT_SALT"]
    )
    assert DEMO_ENV["FEEDBACK_EXPORT_SALT"] not in repr(settings)


@pytest.mark.parametrize(
    "name",
    ["DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER", "FORMAPP_DEPLOYMENT"],
)
def test_form_237_missing_setting_stops_the_job_naming_it(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.delenv(name)

    message = _load_error()

    assert f"{name} is required but not set" in message


@pytest.mark.parametrize(
    "name",
    [
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_AGENT_NAME",
        "FOUNDRY_MODEL",
        "FEEDBACK_EXPORT_CONTAINER_URL",
        "FEEDBACK_EXPORT_SALT",
    ],
)
def test_form_237_demo_requires_foundry_and_export_settings(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.delenv(name)

    message = _load_error()

    assert "must be set in the demo deployment" in message
    assert name in message


def test_form_237_foundry_and_export_settings_are_optional_outside_demo(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("FORMAPP_DEPLOYMENT", "local")
    env.setenv("DATABASE_PASSWORD", "synthetic-local-password")
    env.delenv("AZURE_CLIENT_ID")
    for name in (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_AGENT_NAME",
        "FOUNDRY_MODEL",
        "FEEDBACK_EXPORT_CONTAINER_URL",
        "FEEDBACK_EXPORT_SALT",
    ):
        env.delenv(name)

    settings = load_job_settings()

    assert settings.foundry_project_endpoint is None
    assert settings.feedback_export_salt is None


def test_form_237_demo_requires_verify_full_tls(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_SSLMODE", "require")

    assert "DATABASE_SSLMODE must be verify-full" in _load_error()


def test_form_237_password_in_demo_fails_the_job(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_PASSWORD", "synthetic-password-must-not-print")

    message = _load_error()

    assert "DATABASE_PASSWORD" in message
    assert "synthetic-password-must-not-print" not in message


def test_form_237_entra_sign_in_needs_the_identity_client_id(
    env: pytest.MonkeyPatch,
) -> None:
    env.delenv("AZURE_CLIENT_ID")

    assert "AZURE_CLIENT_ID is required" in _load_error()


def test_form_237_invalid_setting_is_named_without_its_value(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("DATABASE_PORT", "not-a-port-synthetic")

    message = _load_error()

    assert "DATABASE_PORT is invalid" in message
    assert "not-a-port-synthetic" not in message
