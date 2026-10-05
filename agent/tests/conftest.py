"""Shared fixtures: synthetic settings, the stub MCP server and a way to run one agent turn."""

import base64
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evals.scripted_client import ScriptedCall, ScriptedChatClient
from formapp_agent import telemetry
from formapp_agent.host import FormappResponsesHost, build_app
from formapp_agent.settings import Settings
from tests.stub_mcp import STUB_MCP_URL, StubMcp, running_stub


def _synthetic_jwt(n: int) -> str:
    """A JWT-shaped, unsigned synthetic token, built at runtime so no token literal is committed."""

    def part(data: dict[str, str] | str) -> str:
        raw = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    return ".".join(
        (
            part({"alg": "HS256"}),
            part({"pid": f"Synthetic{n}"}),
            part(f"synthetic-signature-{n}"),
        )
    )


# Synthetic turn tokens: never real, and shaped like what api will send.
TURN_1 = _synthetic_jwt(1)
TURN_2 = _synthetic_jwt(2)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "formapp_mcp_url": STUB_MCP_URL,
        "foundry_project_endpoint": "https://foundry.example.test/api/projects/formapp",
        "model_deployment_name": "synthetic-model",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@dataclass
class Harness:
    """A running agent host wired to the stub MCP server and a scripted model."""

    app: FormappResponsesHost
    stub: StubMcp
    model: ScriptedChatClient
    client: httpx.AsyncClient

    async def turn(
        self,
        text: str = "My customer is Ally Macbeal.",
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        sent = dict(headers or {})
        if token is not None:
            sent["x-client-turn-token"] = token
        return await self.client.post(
            "/responses",
            json={"model": "synthetic-model", "input": text, "stream": False},
            headers=sent,
        )


def reply_text(response: httpx.Response) -> str:
    """The assistant text of a non-streamed Responses reply."""
    body = response.json()
    texts = [
        part.get("text", "")
        for item in body.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
    ]
    return "".join(texts)


async def start_harness(
    settings: Settings, steps: Sequence[Sequence[ScriptedCall]], final_text: str
) -> AsyncIterator[Harness]:
    async with running_stub() as (stub, mcp_http):
        model = ScriptedChatClient(steps=steps, final_text=final_text)
        app = build_app(settings, model, http_client=mcp_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent.test",
            timeout=30,
        ) as client:
            yield Harness(app=app, stub=stub, model=model, client=client)
        await app._cleanup_agent()


GET_DRAFT_THEN_PATCH: list[list[ScriptedCall]] = [
    [ScriptedCall("get_draft")],
    [ScriptedCall("patch_draft", {"answers": {"C1": "Ally", "C13": "Macbeal"}})],
]


@pytest.fixture
async def harness(settings: Settings) -> AsyncIterator[Harness]:
    async for h in start_harness(settings, GET_DRAFT_THEN_PATCH, "Filled page 4."):
        yield h


def dump(value: Any) -> str:
    return json.dumps(value, default=str)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# One global tracer provider per process (OpenTelemetry's rule): the agent's own, sampling everything
# for the tests, with an in-memory exporter added.
SPANS = InMemorySpanExporter()


@pytest.fixture(scope="session", autouse=True)
def _state_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    # The hosting package keeps on-disk state under ~/.agentserver unless AGENTSERVER_STATE_ROOT is
    # set; tests must never write outside the repository.
    root = tmp_path_factory.mktemp("agentserver")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AGENTSERVER_STATE_ROOT", str(root))
        yield root


@pytest.fixture(scope="session", autouse=True)
def _tracer_provider() -> None:
    provider = telemetry.build_tracer_provider(
        make_settings(), extra_processors=(SimpleSpanProcessor(SPANS),)
    )
    trace.set_tracer_provider(provider)
    telemetry._provider_set = True
    telemetry.disable_message_capture()


@pytest.fixture
def spans() -> InMemorySpanExporter:
    SPANS.clear()
    return SPANS
