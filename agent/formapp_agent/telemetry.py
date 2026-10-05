"""OpenTelemetry for the agent: sampled traces to Application Insights, no message content (Story 4.2).

The hosting package's default setup would turn on GenAI message capture unless an environment
variable says otherwise, so the host is given this setup instead:

- JSON logs on stdout with redaction (``logging_setup``);
- Agent Framework instrumentation on, with sensitive data (chat text, tool arguments and results,
  which hold answer values) and message events forced off, whatever the host asks for
  (security.md rule 2);
- a tracer provider sampling ``ParentBased(TraceIdRatioBased(TELEMETRY_SAMPLING_RATIO))``: a turn
  that arrives with a ``traceparent`` follows the caller's sampling decision, so one chat turn stays
  one trace (spine Observability);
- the Azure Monitor exporter only when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set; without it
  nothing is exported, and startup logs one ``WARNING`` (naming the variable, never a value) so a
  missing Foundry project Application Insights connection shows up in the container logs.
"""

import logging
from collections.abc import Callable

from azure.core.credentials import TokenCredential
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from formapp_agent.logging_setup import configure_logging
from formapp_agent.settings import Settings

SERVICE = "formapp-agent"

logger = logging.getLogger(__name__)

_provider_set = False


def build_tracer_provider(
    settings: Settings,
    *,
    credential: TokenCredential | None = None,
    extra_processors: tuple[SpanProcessor, ...] = (),
) -> TracerProvider:
    """A sampled tracer provider, exporting to Application Insights only when it is configured."""
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: SERVICE}),
        sampler=ParentBased(TraceIdRatioBased(settings.telemetry_sampling_ratio)),
    )
    connection_string = settings.applicationinsights_connection_string
    if connection_string is not None:
        # Imported only when telemetry is on, so local runs never load the exporter.
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        # Application Insights has local authentication off: ingestion is authorised by the
        # agent identity's Entra token.
        exporter = AzureMonitorTraceExporter(
            connection_string=connection_string.get_secret_value(),
            credential=credential,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
    for processor in extra_processors:
        provider.add_span_processor(processor)
    return provider


def disable_message_capture() -> None:
    """Keep Agent Framework spans on but free of chat text and tool arguments (security.md rule 2)."""
    from agent_framework.observability import enable_instrumentation

    enable_instrumentation(enable_sensitive_data=False, enable_message_events=False)


def observability_setup(
    settings: Settings, *, credential: TokenCredential | None = None
) -> Callable[..., None]:
    """The ``configure_observability`` callable for the host, bound to these settings."""

    def configure(
        *,
        connection_string: str | None = None,
        log_level: str | None = None,
        enable_sensitive_data: bool = False,
    ) -> None:
        # The host's arguments are ignored on purpose: the settings decide the exporter and the log
        # level, and message capture is never enabled, whatever the environment says.
        del connection_string, log_level, enable_sensitive_data
        global _provider_set
        configure_logging(settings.log_level)
        disable_message_capture()
        if not _provider_set:
            if settings.applicationinsights_connection_string is None:
                # Foundry injects this variable only when the project has an Application Insights
                # connection (Microsoft Learn, "Export hosted agent telemetry by using
                # OpenTelemetry"); missing it here almost always means that connection is missing
                # or misconfigured. Named, never valued (NFR17): there is no value to log.
                logger.warning(
                    "APPLICATIONINSIGHTS_CONNECTION_STRING is not set; telemetry export is off"
                )
            # OpenTelemetry allows one global provider per process.
            trace.set_tracer_provider(
                build_tracer_provider(settings, credential=credential)
            )
            _provider_set = True

    return configure
