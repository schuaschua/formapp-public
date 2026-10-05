"""Start the hosted agent: ``python -m formapp_agent.main`` (the image's command).

Serves ``POST /responses`` and ``GET /readiness`` on ``PORT`` (8088 by default). Settings come only
from the environment; a missing or invalid one stops startup, naming the variable but never its
value. Foundry and telemetry ingestion sign in with the default Azure credential chain (the
platform's managed identity in Azure); there are no keys.
"""

import sys

from agent_framework_foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from formapp_agent.host import FormappResponsesHost, build_app
from formapp_agent.settings import Settings, SettingsError, load_settings
from formapp_agent.telemetry import observability_setup


def create_app(settings: Settings) -> FormappResponsesHost:
    """The agent server for these settings, talking to the configured Foundry model deployment."""
    credential = DefaultAzureCredential(
        managed_identity_client_id=settings.azure_client_id
    )
    chat_client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.model_deployment_name,
        credential=credential,
    )
    return build_app(
        settings,
        chat_client,
        configure_observability=observability_setup(settings, credential=credential),
    )


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    create_app(settings).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
