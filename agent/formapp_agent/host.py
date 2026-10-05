"""The hosted agent: one Agent Framework agent behind the Foundry Responses host (Story 4.2).

The agent's only tool source is one ``MCPStreamableHTTPTool`` pointed at the api ``/mcp`` URL,
limited to the AD-3 tool names (AD-1, AD-3, azure.md rule 26). It has no other Foundry tools,
connections or database credentials.

The turn token: the host passes the request's ``x-client-*`` headers to ``_handle_response`` in
``ResponseContext.client_headers`` but not to ``agent.run``, so ``_handle_response`` is the seam.
It puts the token in the turn's ``ContextVar`` for the length of the turn, and the tool's
``header_provider`` sends it as ``Authorization: Bearer`` (AD-4). Without a token the turn ends with
a fixed reply before the agent, the model or the MCP server is touched; the hosting library creates
no span of its own for the request, so this module opens one explicitly for that path (a reason code
only, Story 4.2's telemetry fix), so a Foundry playground call with no signed-in user still produces
a trace. The hosting package is a pinned beta; a test fails if this hook stops receiving the headers,
so recheck it on every bump.
"""

import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
from agent_framework import Agent, MCPStreamableHTTPTool, SupportsChatGetResponse
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses import ResponseContext
from azure.ai.agentserver.responses.aio import ResponseEventStream
from azure.ai.agentserver.responses.models import CreateResponse, ResponseStreamEvent
from azure.ai.agentserver.responses.streaming._checkpoint import ResponseCheckpointEvent
from opentelemetry import trace

from formapp_agent.settings import Settings
from formapp_agent.telemetry import observability_setup
from formapp_agent.turn_token import (
    header_provider,
    token_from_headers,
    turn_token_scope,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# AD-3: the complete MCP tool surface. find_customer and link_customer arrive in Epic 5; anything
# else the server offers is never shown to the model.
AD3_TOOL_NAMES: tuple[str, ...] = (
    "get_form_schema",
    "get_products",
    "get_draft",
    "patch_draft",
    "validate_draft",
    "find_customer",
    "link_customer",
)

MCP_TOOL_NAME = "formapp"

# The failure copy from EXPERIENCE.md, used when a turn can't run at all.
FAILED_TURN_REPLY = (
    "The AI couldn't finish. Answers so far are saved. Please try again."
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT = PROMPTS_DIR / "system.md"

ObservabilitySetup = Callable[..., None]


def load_instructions(path: Path = SYSTEM_PROMPT) -> str:
    """The agent's instructions, from the prompt file versioned in git (NFR24)."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"The prompt file {path.name} is empty")
    return text


def build_mcp_tool(
    settings: Settings, http_client: httpx.AsyncClient | None = None
) -> MCPStreamableHTTPTool:
    """The one tool source: the api MCP server, sending the turn token as a bearer token."""
    return MCPStreamableHTTPTool(
        name=MCP_TOOL_NAME,
        url=settings.formapp_mcp_url,
        description="The formapp proposal the insurance agent is filling in.",
        allowed_tools=AD3_TOOL_NAMES,
        # Prompts live in agent/prompts/ in git, never on the server.
        load_prompts=False,
        header_provider=header_provider,
        http_client=http_client,
    )


def build_agent(
    settings: Settings,
    chat_client: SupportsChatGetResponse[Any],
    *,
    http_client: httpx.AsyncClient | None = None,
    instructions: str | None = None,
) -> Agent[Any]:
    """The formapp agent: the system prompt and the one MCP tool."""
    return Agent(
        client=chat_client,
        name="formapp-agent",
        instructions=instructions if instructions is not None else load_instructions(),
        tools=[build_mcp_tool(settings, http_client)],
    )


class FormappResponsesHost(ResponsesHostServer):
    """The Responses host, with the turn token taken from the request for each turn (AD-4)."""

    def _build_hypercorn_config(self, host: str, port: int) -> object:
        config = super()._build_hypercorn_config(host, port)
        # Hypercorn's default error log ("-") installs its own stream handler, bypassing the JSON
        # formatter and the redaction filter; a Logger is used as it is, so records propagate to
        # the redacting root handler instead.
        config.errorlog = logging.getLogger("hypercorn.error")  # type: ignore[attr-defined]
        return config

    async def _handle_response(
        self,
        request: CreateResponse,
        context: ResponseContext,
        cancellation_signal: asyncio.Event,
    ) -> AsyncIterable[ResponseStreamEvent | ResponseCheckpointEvent]:
        token = token_from_headers(context.client_headers)
        if token is None:
            # Header names only, never values (security.md rules 7, 30).
            logger.warning(
                "Turn refused: no turn token",
                extra={"client_header_names": sorted(context.client_headers or {})},
            )
            # The hosting library's own request handling creates no span of its own (its
            # create_response "span" is bookkeeping only, never an OTel span); without this, a
            # turn that never reaches agent.run (every no-token turn) produced no trace at all, so a
            # Foundry playground call with no signed-in user looked like telemetry was broken rather
            # than working as designed. This span joins the incoming trace context, the same way the
            # agent's own spans do, and carries a reason code only, never header names or values
            # (security.md rules 2, 7, 30).
            with _tracer.start_as_current_span(
                "agent.turn_refused",
                attributes={"formapp.turn.refused_reason": "no_turn_token"},
            ):
                async for event in _fixed_reply(context, FAILED_TURN_REPLY):
                    yield event
            return
        with turn_token_scope(token):
            async for event in super()._handle_response(
                request, context, cancellation_signal
            ):
                yield event


async def _fixed_reply(
    context: ResponseContext, text: str
) -> AsyncIterator[ResponseStreamEvent]:
    """A complete response holding one assistant message, with no model or tool call."""
    stream = ResponseEventStream(response_id=context.response_id)
    yield stream.emit_created()
    yield stream.emit_in_progress()
    async for event in stream.output_item_message(text):
        yield event
    yield stream.emit_completed()


def build_app(
    settings: Settings,
    chat_client: SupportsChatGetResponse[Any],
    http_client: httpx.AsyncClient | None = None,
    *,
    configure_observability: ObservabilitySetup | None = None,
) -> FormappResponsesHost:
    """The agent server: ``POST /responses`` and ``GET /readiness`` (a Starlette app).

    Without ``configure_observability`` the agent's own setup is used (redacted JSON logs, no
    message capture); the hosting package's default is never used, since it turns capture on.
    """
    if configure_observability is None:
        configure_observability = observability_setup(settings)
    connection_string = settings.applicationinsights_connection_string
    return FormappResponsesHost(
        build_agent(settings, chat_client, http_client=http_client),
        applicationinsights_connection_string=(
            connection_string.get_secret_value() if connection_string else None
        ),
        configure_observability=configure_observability,
        log_level=settings.log_level,
    )
