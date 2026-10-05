"""Story 4.2: settings come only from the environment, and bad ones stop startup by name."""

import pytest
from pydantic import ValidationError

from formapp_agent.settings import Settings, SettingsError, load_settings

VALID_ENV = {
    "FORMAPP_MCP_URL": "https://ca-formapp-demo.example.test/mcp",
    "FOUNDRY_PROJECT_ENDPOINT": "https://aif-formapp.example.test/api/projects/formapp",
    "MODEL_DEPLOYMENT_NAME": "synthetic-deployment-name",
}
CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
    "IngestionEndpoint=https://ingest.example.test/"
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        *VALID_ENV,
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "AZURE_CLIENT_ID",
        "TELEMETRY_SAMPLING_RATIO",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_story_4_2_model_deployment_name_comes_from_env(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("MODEL_DEPLOYMENT_NAME", "another-synthetic-deployment")

    settings = load_settings()

    assert settings.model_deployment_name == "another-synthetic-deployment"
    assert settings.formapp_mcp_url == VALID_ENV["FORMAPP_MCP_URL"]
    assert settings.applicationinsights_connection_string is None
    assert settings.telemetry_sampling_ratio == 1.0


@pytest.mark.parametrize("missing", sorted(VALID_ENV))
def test_story_4_2_missing_setting_stops_startup_naming_it(
    env: pytest.MonkeyPatch, missing: str
) -> None:
    env.delenv(missing)

    with pytest.raises(SettingsError) as raised:
        load_settings()

    message = str(raised.value)
    assert f"{missing} is required but not set" in message
    for value in VALID_ENV.values():
        assert value not in message


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FORMAPP_MCP_URL", "http://ca-formapp-demo.example.test/mcp"),
        ("FORMAPP_MCP_URL", "https://user:synthetic-pass@ca.example.test/mcp"),
        ("FORMAPP_MCP_URL", "not a url"),
        ("FORMAPP_MCP_URL", "https://[bad/mcp"),
        ("FOUNDRY_PROJECT_ENDPOINT", "http://localhost:9000/api/projects/p"),
        ("MODEL_DEPLOYMENT_NAME", "   "),
        ("TELEMETRY_SAMPLING_RATIO", "1.5"),
        (
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "InstrumentationKey=synthetic-not-a-guid",
        ),
        ("APPLICATIONINSIGHTS_CONNECTION_STRING", "no-pairs-synthetic"),
        (
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            (
                "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
                "IngestionEndpoint=http://ingest.example.test/"
            ),
        ),
    ],
)
def test_story_4_2_invalid_setting_named_never_printed(
    env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    env.setenv(name, value)

    with pytest.raises(SettingsError) as raised:
        load_settings()

    message = str(raised.value)
    assert f"{name} is invalid" in message
    if value.strip():
        assert value not in message


def test_story_4_2_mcp_url_allows_http_only_on_loopback(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("FORMAPP_MCP_URL", "http://localhost:8080/mcp")

    assert load_settings().formapp_mcp_url == "http://localhost:8080/mcp"


def test_story_4_2_blank_optional_settings_are_unset(env: pytest.MonkeyPatch) -> None:
    env.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", " ")
    env.setenv("AZURE_CLIENT_ID", "")
    env.setenv("LOG_LEVEL", "debug")

    settings = load_settings()

    assert settings.applicationinsights_connection_string is None
    assert settings.azure_client_id is None
    assert settings.log_level == "DEBUG"


def test_story_4_2_connection_string_kept_secret(env: pytest.MonkeyPatch) -> None:
    env.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", CONNECTION_STRING)

    settings = load_settings()

    assert settings.applicationinsights_connection_string is not None
    assert CONNECTION_STRING not in repr(settings)


def test_story_4_2_settings_are_frozen(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()

    with pytest.raises(ValidationError):
        settings.model_deployment_name = "changed"  # type: ignore[misc]  # frozen on purpose
    assert isinstance(settings, Settings)
