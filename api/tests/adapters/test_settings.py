"""Story 1.3: configuration comes only from environment variables, with startup guards."""

import pytest

from adapters.rest.app import create_app
from adapters.settings import SettingsError, load_settings
from tests.support import TEST_SIGNING_KEY

# Distinctive synthetic values, so a test can prove none of them is ever printed.
DEMO_ENV = {
    "FORMAPP_DEPLOYMENT": "demo",
    "DATABASE_HOST": "pgsql-synthetic-host.example.test",
    "DATABASE_NAME": "formapp",
    "DATABASE_USER": "id-synthetic-api",
    "AZURE_CLIENT_ID": "00000000-1111-2222-3333-444444444444",
    "DB_MIGRATION_ROLE": "formapp_migrator",
    "TURN_TOKEN_SIGNING_KEY": TEST_SIGNING_KEY,
    "FOUNDRY_PROJECT_ENDPOINT": "https://synthetic-foundry.example.test/api/projects/formapp",
    "FOUNDRY_AGENT_NAME": "formapp-agent",
    "FOUNDRY_MODEL": "synthetic-model-deployment",
    "SPEECH_REGION": "southeastasia",
    "SPEECH_ENDPOINT": "https://cog-sample-demo-sea.cognitiveservices.azure.com",
    "SPEECH_RESOURCE_ID": (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
        "rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/"
        "cog-sample-demo-sea"
    ),
    "SPEECH_IDENTITY_CLIENT_ID": "00000000-6666-7777-8888-999999999999",
    "SPEECH_LOCALE": "en-SG",
    "SPEECH_VOICE": "en-SG-LunaNeural",
}
SETTING_NAMES = [
    "FORMAPP_DEPLOYMENT",
    "DATABASE_HOST",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PORT",
    "DATABASE_SSLMODE",
    "DATABASE_PASSWORD",
    "DB_MIGRATION_ROLE",
    "AZURE_CLIENT_ID",
    "TURN_TOKEN_SIGNING_KEY",
    "FORMAPP_TEST_MODE",
    "FORMAPP_STATIC_DIR",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "TELEMETRY_SAMPLING_RATIO",
    "LOG_LEVEL",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_AGENT_NAME",
    "FOUNDRY_MODEL",
    "SPEECH_REGION",
    "SPEECH_ENDPOINT",
    "SPEECH_RESOURCE_ID",
    "SPEECH_IDENTITY_CLIENT_ID",
    "SPEECH_LOCALE",
    "SPEECH_VOICE",
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
    with pytest.raises(SettingsError) as caught:
        load_settings()
    return str(caught.value)


def _assert_no_values(message: str) -> None:
    for value in DEMO_ENV.values():
        if value not in ("demo", "formapp", "formapp_migrator"):
            assert value not in message


def test_story_1_3_settings_come_from_environment_variables(
    env: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert settings.is_demo
    assert settings.database_host == DEMO_ENV["DATABASE_HOST"]
    assert settings.database_name == "formapp"
    assert settings.database_user == DEMO_ENV["DATABASE_USER"]
    assert settings.azure_client_id == DEMO_ENV["AZURE_CLIENT_ID"]
    assert settings.database_sslmode == "verify-full"
    assert settings.db_migration_role == "formapp_migrator"
    assert settings.database_password is None
    assert settings.formapp_test_mode is False


def test_story_1_3_signing_key_is_read_from_the_settings_object(
    env: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert settings.turn_token_signing_key.get_secret_value() == TEST_SIGNING_KEY
    assert TEST_SIGNING_KEY not in repr(settings)


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_HOST",
        "DATABASE_NAME",
        "DATABASE_USER",
        "TURN_TOKEN_SIGNING_KEY",
        "FORMAPP_DEPLOYMENT",
        "DB_MIGRATION_ROLE",
    ],
)
def test_story_1_3_missing_setting_stops_startup_naming_it(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.delenv(name)

    message = _load_error()

    assert f"{name} is required but not set" in message
    _assert_no_values(message)


def test_story_1_3_invalid_setting_is_named_without_its_value(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("DATABASE_PORT", "not-a-port-synthetic")

    message = _load_error()

    assert "DATABASE_PORT is invalid" in message
    assert "not-a-port-synthetic" not in message


def test_story_1_3_app_startup_stops_on_missing_setting(
    env: pytest.MonkeyPatch,
) -> None:
    env.delenv("DATABASE_HOST")

    with pytest.raises(SettingsError, match="DATABASE_HOST"):
        create_app()


def test_story_1_3_test_mode_in_demo_fails_startup(env: pytest.MonkeyPatch) -> None:
    env.setenv("FORMAPP_TEST_MODE", "true")

    message = _load_error()

    assert "FORMAPP_TEST_MODE" in message
    with pytest.raises(SettingsError, match="FORMAPP_TEST_MODE"):
        create_app()


def test_story_1_3_test_mode_is_allowed_outside_demo(env: pytest.MonkeyPatch) -> None:
    env.setenv("FORMAPP_DEPLOYMENT", "local")
    env.setenv("FORMAPP_TEST_MODE", "true")

    assert load_settings().formapp_test_mode is True


def test_story_1_3_password_in_demo_fails_startup(env: pytest.MonkeyPatch) -> None:
    env.setenv("DATABASE_PASSWORD", "synthetic-password-must-not-print")

    message = _load_error()

    assert "DATABASE_PASSWORD" in message
    assert "synthetic-password-must-not-print" not in message


def test_story_1_3_password_is_allowed_outside_demo(env: pytest.MonkeyPatch) -> None:
    env.setenv("FORMAPP_DEPLOYMENT", "local")
    env.setenv("DATABASE_PASSWORD", "synthetic-local-password")
    env.delenv("AZURE_CLIENT_ID")

    settings = load_settings()

    assert settings.database_password is not None
    assert "synthetic-local-password" not in repr(settings)


@pytest.mark.parametrize("sslmode", ["disable", "prefer", "require", "verify-ca"])
def test_story_1_3_demo_requires_verify_full_tls(
    env: pytest.MonkeyPatch, sslmode: str
) -> None:
    env.setenv("DATABASE_SSLMODE", sslmode)

    assert "DATABASE_SSLMODE must be verify-full" in _load_error()


def test_story_1_3_entra_sign_in_needs_the_identity_client_id(
    env: pytest.MonkeyPatch,
) -> None:
    env.delenv("AZURE_CLIENT_ID")

    assert "AZURE_CLIENT_ID is required" in _load_error()


def test_story_1_5_telemetry_settings_come_from_environment_variables(
    env: pytest.MonkeyPatch,
) -> None:
    connection_string = (
        "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;"
        "IngestionEndpoint=https://synthetic-ingest.example.test/"
    )
    env.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", connection_string)
    env.setenv("TELEMETRY_SAMPLING_RATIO", "0.5")

    settings = load_settings()

    assert settings.telemetry_sampling_ratio == 0.5
    assert settings.applicationinsights_connection_string is not None
    assert (
        settings.applicationinsights_connection_string.get_secret_value()
        == connection_string
    )
    assert connection_string not in repr(settings)


def test_story_1_5_telemetry_is_optional(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()

    assert settings.applicationinsights_connection_string is None
    assert settings.telemetry_sampling_ratio == 1.0


@pytest.mark.parametrize("ratio", ["1.5", "-0.1", "nan", "inf", "half"])
def test_story_1_5_invalid_sampling_ratio_stops_startup_naming_it(
    env: pytest.MonkeyPatch, ratio: str
) -> None:
    env.setenv("TELEMETRY_SAMPLING_RATIO", ratio)

    message = _load_error()

    assert "TELEMETRY_SAMPLING_RATIO is invalid" in message
    with pytest.raises(SettingsError, match="TELEMETRY_SAMPLING_RATIO"):
        create_app()


@pytest.mark.parametrize(
    "value",
    [
        "not-a-connection-string",
        "InstrumentationKey=synthetic-not-a-guid",
        "IngestionEndpoint=https://synthetic-ingest.example.test/",
        (
            "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;"
            "IngestionEndpoint=http://synthetic-ingest.example.test/"
        ),
    ],
)
def test_story_1_5_malformed_connection_string_stops_startup_naming_it(
    env: pytest.MonkeyPatch, value: str
) -> None:
    env.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", value)

    message = _load_error()

    assert "APPLICATIONINSIGHTS_CONNECTION_STRING is invalid" in message
    assert "synthetic" not in message
    assert "c0de" not in message


def test_story_1_5_log_level_defaults_to_info_and_is_read(
    env: pytest.MonkeyPatch,
) -> None:
    assert load_settings().log_level == "INFO"

    env.setenv("LOG_LEVEL", "warning")

    assert load_settings().log_level == "WARNING"


def test_story_1_5_invalid_log_level_stops_startup_naming_it(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("LOG_LEVEL", "chatty")

    assert "LOG_LEVEL is invalid" in _load_error()


def test_story_4_5_foundry_settings_come_from_environment_variables(
    env: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert settings.foundry_project_endpoint == DEMO_ENV["FOUNDRY_PROJECT_ENDPOINT"]
    assert settings.foundry_agent_name == DEMO_ENV["FOUNDRY_AGENT_NAME"]
    # Story 4.9: also the model deployment name logged on every answer_overrides row (AD-17).
    assert settings.foundry_model == DEMO_ENV["FOUNDRY_MODEL"]


@pytest.mark.parametrize(
    "name",
    ["FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_AGENT_NAME", "FOUNDRY_MODEL"],
)
def test_story_4_5_demo_requires_foundry_settings(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.delenv(name)

    message = _load_error()

    assert "must be set in the demo deployment" in message
    assert name in message


def test_story_4_5_foundry_settings_are_optional_outside_demo(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("FORMAPP_DEPLOYMENT", "local")
    env.setenv("FORMAPP_TEST_MODE", "true")
    env.delenv("FOUNDRY_PROJECT_ENDPOINT")
    env.delenv("FOUNDRY_AGENT_NAME")
    env.delenv("FOUNDRY_MODEL")

    settings = load_settings()

    assert settings.foundry_project_endpoint is None
    # Story 4.9: the REST call site (patch_answers), not Settings, turns this None into a
    # grep-able placeholder before it reaches the domain layer -- see test_proposals.py.
    assert settings.foundry_model is None


def test_story_6_1_speech_settings_come_from_environment_variables(
    env: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert settings.speech_region == DEMO_ENV["SPEECH_REGION"]
    assert settings.speech_endpoint == DEMO_ENV["SPEECH_ENDPOINT"]
    assert settings.speech_resource_id == DEMO_ENV["SPEECH_RESOURCE_ID"]
    assert settings.speech_identity_client_id == DEMO_ENV["SPEECH_IDENTITY_CLIENT_ID"]
    assert settings.speech_locale == DEMO_ENV["SPEECH_LOCALE"]
    assert settings.speech_voice == DEMO_ENV["SPEECH_VOICE"]


@pytest.mark.parametrize(
    "name",
    [
        "SPEECH_REGION",
        "SPEECH_ENDPOINT",
        "SPEECH_RESOURCE_ID",
        "SPEECH_IDENTITY_CLIENT_ID",
        "SPEECH_LOCALE",
        "SPEECH_VOICE",
    ],
)
def test_story_6_1_demo_requires_speech_settings(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.delenv(name)

    message = _load_error()

    assert "must be set in the demo deployment" in message
    assert name in message


def test_story_6_1_speech_settings_are_optional_outside_demo(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("FORMAPP_DEPLOYMENT", "local")
    env.setenv("FORMAPP_TEST_MODE", "true")
    for name in (
        "SPEECH_REGION",
        "SPEECH_ENDPOINT",
        "SPEECH_RESOURCE_ID",
        "SPEECH_IDENTITY_CLIENT_ID",
        "SPEECH_LOCALE",
        "SPEECH_VOICE",
    ):
        env.delenv(name)

    settings = load_settings()

    assert settings.speech_region is None
    assert settings.speech_voice is None


def test_story_1_5_demo_telemetry_needs_the_managed_identity(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de",
    )
    env.delenv("AZURE_CLIENT_ID")

    message = _load_error()

    assert (
        "AZURE_CLIENT_ID is required when APPLICATIONINSIGHTS_CONNECTION_STRING"
        in message
    )
    assert "c0de" not in message
