"""Story 4.2: the turn token reaches the MCP server only as a bearer token, and never elsewhere."""

import json
import logging
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evals.scripted_client import ScriptedCall
from formapp_agent.host import (
    AD3_TOOL_NAMES,
    FAILED_TURN_REPLY,
    SYSTEM_PROMPT,
    build_agent,
    load_instructions,
)
from formapp_agent.logging_setup import configure_logging
from formapp_agent.settings import Settings
from formapp_agent.turn_token import header_provider, token_from_headers
from tests.conftest import (
    GET_DRAFT_THEN_PATCH,
    TURN_1,
    TURN_2,
    Harness,
    reply_text,
    start_harness,
)
from tests.stub_mcp import NOT_AD3_TOOL

pytestmark = pytest.mark.anyio

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"


async def test_story_4_2_turn_token_sent_to_mcp_as_bearer(harness: Harness) -> None:
    response = await harness.turn(token=TURN_1)

    assert response.status_code == 200
    assert reply_text(response) == "Filled page 4."
    # Every request, the handshake and discovery included, carries the turn's token.
    assert harness.stub.requests
    assert set(harness.stub.authorizations()) == {f"Bearer {TURN_1}"}
    assert harness.stub.tool_calls == [
        ("get_draft", {}),
        ("patch_draft", {"answers": {"C1": "Ally", "C13": "Macbeal"}}),
    ]


async def test_story_4_2_header_hook_receives_client_headers_in_any_case(
    harness: Harness,
) -> None:
    # Recheck on every hosting beta bump: if the host stops passing x-client-* headers to
    # _handle_response, every turn would get the no-token reply and this test fails.
    response = await harness.turn(headers={"X-Client-Turn-Token": TURN_1})

    assert reply_text(response) == "Filled page 4."
    assert set(harness.stub.tool_call_authorizations()) == {f"Bearer {TURN_1}"}


async def test_story_4_2_reply_streams(harness: Harness) -> None:
    response = await harness.client.post(
        "/responses",
        json={"model": "synthetic-model", "input": "Ally Macbeal", "stream": True},
        headers={"x-client-turn-token": TURN_1},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "response.output_text.delta" in response.text
    assert "Filled page 4." in response.text
    assert set(harness.stub.tool_call_authorizations()) == {f"Bearer {TURN_1}"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-client-turn-token": ""},
        {"x-client-turn-token": "   "},
        {"x-client-session": "synthetic-session-value"},
    ],
    ids=["missing", "empty", "blank", "other-client-header"],
)
async def test_story_4_2_no_token_gives_fixed_reply_without_mcp_or_model(
    harness: Harness,
    headers: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(logging.DEBUG)

    response = await harness.turn(headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert reply_text(response) == FAILED_TURN_REPLY
    assert harness.stub.requests == []
    assert harness.model.requests == []
    logs = capsys.readouterr().out
    assert "Turn refused: no turn token" in logs
    assert "synthetic-session-value" not in logs


async def test_story_4_2_no_token_turn_still_produces_a_trace(
    harness: Harness, spans: InMemorySpanExporter
) -> None:
    # Without this, a turn that never reaches agent.run (every no-token turn) produced no span at
    # all: a Foundry playground call with no signed-in user looked like telemetry was broken.
    await harness.turn(headers={"traceparent": TRACEPARENT})

    finished = spans.get_finished_spans()
    (span,) = [s for s in finished if s.name == "agent.turn_refused"]
    assert format(span.context.trace_id, "032x") == TRACE_ID
    attributes = dict(span.attributes or {})
    assert attributes == {"formapp.turn.refused_reason": "no_turn_token"}


async def test_story_4_2_each_turn_carries_only_its_own_token(
    settings: Settings,
) -> None:
    async for harness in start_harness(settings, GET_DRAFT_THEN_PATCH, "Done."):
        await harness.turn(token=TURN_1)
        first = len(harness.stub.requests)
        await harness.turn(token=TURN_2)

        turn_1 = harness.stub.authorizations()[:first]
        turn_2 = harness.stub.authorizations()[first:]
        assert set(turn_1) == {f"Bearer {TURN_1}"}
        # The tool reconnected with the new token: nothing from turn 1 is reused.
        assert set(turn_2) == {f"Bearer {TURN_2}"}
        assert [r.rpc_method for r in harness.stub.requests[first:]].count(
            "tools/call"
        ) == 2
        assert harness.stub.requests[first].rpc_method == "initialize"


async def test_story_4_2_turn_after_no_token_turn_still_works(harness: Harness) -> None:
    await harness.turn()
    response = await harness.turn(token=TURN_1)

    assert reply_text(response) == "Filled page 4."
    assert set(harness.stub.authorizations()) == {f"Bearer {TURN_1}"}


async def test_story_4_2_token_absent_from_model_input_reply_and_logs(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    spans: InMemorySpanExporter,
) -> None:
    configure_logging(logging.DEBUG)

    response = await harness.turn(token=TURN_1)

    assert harness.model.requests
    for request in harness.model.requests:
        assert TURN_1 not in request.text()
    assert TURN_1 not in response.text
    body = response.json()
    assert TURN_1 not in json.dumps(body.get("metadata"))
    logs = capsys.readouterr().out
    assert logs
    assert TURN_1 not in logs
    for span in spans.get_finished_spans():
        assert TURN_1 not in json.dumps(dict(span.attributes or {}), default=str)
        for event in span.events:
            assert TURN_1 not in json.dumps(dict(event.attributes or {}), default=str)


async def test_story_4_2_spans_join_incoming_trace_without_message_content(
    harness: Harness, spans: InMemorySpanExporter
) -> None:
    await harness.turn(token=TURN_1, headers={"traceparent": TRACEPARENT})

    finished = spans.get_finished_spans()
    assert finished
    trace_ids = {format(span.context.trace_id, "032x") for span in finished}
    assert trace_ids == {TRACE_ID}
    names = " ".join(span.name for span in finished)
    assert "get_draft" in names and "patch_draft" in names
    # Message capture is off: no chat text, tool arguments or answer values on any span.
    for span in finished:
        attributes = json.dumps(dict(span.attributes or {}), default=str)
        assert "Macbeal" not in attributes
        assert "gen_ai.input.messages" not in attributes
        assert "gen_ai.tool.call.arguments" not in attributes


async def test_story_4_2_model_sees_only_ad3_tools(harness: Harness) -> None:
    await harness.turn(token=TURN_1)

    tools = harness.model.requests[0].options.get("tools") or []
    names = {getattr(tool, "name", None) for tool in tools}
    assert names <= set(AD3_TOOL_NAMES)
    assert {"get_draft", "patch_draft"} <= names
    assert NOT_AD3_TOOL not in names


async def test_story_4_2_tool_outside_ad3_is_never_called(settings: Settings) -> None:
    steps = [[ScriptedCall(NOT_AD3_TOOL)]]
    async for harness in start_harness(settings, steps, "Done."):
        await harness.turn(token=TURN_1)

        assert (NOT_AD3_TOOL, {}) not in harness.stub.tool_calls


async def test_story_4_2_instructions_come_from_prompt_file(harness: Harness) -> None:
    await harness.turn(token=TURN_1)

    prompt = SYSTEM_PROMPT.read_text(encoding="utf-8").strip()
    assert harness.model.requests[0].options.get("instructions") == prompt


def test_story_4_2_only_tool_source_is_one_mcp_tool(settings: Settings) -> None:
    from agent_framework import MCPStreamableHTTPTool

    from evals.scripted_client import ScriptedChatClient

    agent = build_agent(settings, ScriptedChatClient())
    # No local function tools and no other tool source: only the one MCP tool.
    assert not agent.default_options.get("tools")
    assert len(agent.mcp_tools) == 1
    (tool,) = agent.mcp_tools
    assert isinstance(tool, MCPStreamableHTTPTool)
    assert tool.url == settings.formapp_mcp_url
    assert tuple(tool.allowed_tools or ()) == AD3_TOOL_NAMES
    assert AD3_TOOL_NAMES == (
        "get_form_schema",
        "get_products",
        "get_draft",
        "patch_draft",
        "validate_draft",
        "find_customer",
        "link_customer",
    )


def test_story_4_2_prompt_loading(tmp_path_factory: pytest.TempPathFactory) -> None:
    text = load_instructions()
    assert "patch_draft" in text
    assert "D1" in text

    empty = tmp_path_factory.mktemp("prompts") / "system.md"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_instructions(empty)


def test_story_4_2_header_provider_uses_only_the_turn_scope() -> None:
    from formapp_agent.turn_token import turn_token_scope

    assert header_provider({}) == {}
    with turn_token_scope(TURN_1):
        # Run arguments are ignored: a token passed there would reach the tool arguments too.
        assert header_provider({"token": "other"}) == {
            "Authorization": f"Bearer {TURN_1}"
        }
    assert header_provider({}) == {}
    assert token_from_headers(None) is None
    assert token_from_headers({"x-client-turn-token": f" {TURN_2} "}) == TURN_2


async def test_story_4_2_host_state_stays_under_state_root(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, _state_root: Path
) -> None:
    from azure.ai.agentserver.core._config import resolve_state_subdir

    def no_home() -> Path:
        raise AssertionError("the host must not use the home directory")

    monkeypatch.setattr(Path, "home", staticmethod(no_home))

    assert resolve_state_subdir("responses").is_relative_to(_state_root)
    async for harness in start_harness(settings, GET_DRAFT_THEN_PATCH, "Done."):
        response = await harness.turn(token=TURN_1)
        assert reply_text(response) == "Done."


def test_story_4_2_server_error_log_goes_through_redacting_root(
    settings: Settings,
) -> None:
    from hypercorn.logging import Logger as HypercornLogger

    from evals.scripted_client import ScriptedChatClient
    from formapp_agent.host import build_app

    app = build_app(settings, ScriptedChatClient())
    config = app._build_hypercorn_config("127.0.0.1", 8088)

    error_logger = logging.getLogger("hypercorn.error")
    assert config.errorlog is error_logger  # type: ignore[attr-defined]
    # Hypercorn uses a Logger as it is: no stream handler of its own, records reach the root.
    assert HypercornLogger(config).error_logger is error_logger  # type: ignore[arg-type]
    assert error_logger.handlers == []
    assert error_logger.propagate
