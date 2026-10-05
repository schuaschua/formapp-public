"""An in-process stand-in for the api MCP server that records every request's headers.

Built with the ``mcp`` 1.x ``FastMCP`` streamable HTTP app and reached through
``httpx.ASGITransport``, so no socket, api or Azure is involved. It offers the Epic 4 AD-3 tools
plus one tool outside AD-3, which the agent must never show to the model.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The URL the agent is configured with; https like demo, served in process.
STUB_MCP_URL = "https://stub-mcp.test/mcp"
# A tool the stub offers that is not in AD-3.
NOT_AD3_TOOL = "drop_all_proposals"


@dataclass
class RecordedRequest:
    method: str
    headers: dict[str, str]
    body: bytes

    @property
    def rpc_method(self) -> str | None:
        try:
            return json.loads(self.body).get("method")
        except (ValueError, AttributeError):
            return None


@dataclass
class StubMcp:
    """The stub server's app and everything it has received."""

    app: ASGIApp
    server: FastMCP
    requests: list[RecordedRequest] = field(default_factory=list)
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def authorizations(self) -> list[str | None]:
        """The Authorization header of every request, in order (None when absent)."""
        return [request.headers.get("authorization") for request in self.requests]

    def tool_call_authorizations(self) -> list[str | None]:
        """The Authorization header of every ``tools/call`` request, in order."""
        return [
            request.headers.get("authorization")
            for request in self.requests
            if request.rpc_method == "tools/call"
        ]


class _RecordingMiddleware:
    def __init__(self, app: ASGIApp, stub: StubMcp) -> None:
        self.app = app
        self.stub = stub

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope["headers"]
        }
        self.stub.requests.append(RecordedRequest(scope["method"], headers, body))
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def build_stub() -> StubMcp:
    server = FastMCP(
        "formapp-stub",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    stub = StubMcp(app=server.streamable_http_app(), server=server)

    @server.tool()
    def get_form_schema() -> dict[str, Any]:
        """The proposal's pinned form schema."""
        stub.tool_calls.append(("get_form_schema", {}))
        return {"schema_version": 1, "pages": ["Needs", "Product", "Payment"]}

    @server.tool()
    def get_draft() -> dict[str, Any]:
        """The current draft."""
        stub.tool_calls.append(("get_draft", {}))
        return {"revision": 1, "answers": {}}

    @server.tool()
    def patch_draft(answers: dict[str, Any]) -> dict[str, Any]:
        """Apply answers to the draft."""
        stub.tool_calls.append(("patch_draft", {"answers": answers}))
        return {"applied": sorted(answers), "errors": [], "revision": 2}

    @server.tool()
    def validate_draft() -> dict[str, Any]:
        """Validate the draft."""
        stub.tool_calls.append(("validate_draft", {}))
        return {"errors": []}

    @server.tool()
    def get_products() -> list[dict[str, Any]]:
        """Products for the insured's age."""
        stub.tool_calls.append(("get_products", {}))
        return [{"code": "FSH", "name": "FamilyShield Life & Health"}]

    @server.tool(name=NOT_AD3_TOOL)
    def drop_all_proposals() -> str:
        """Not an AD-3 tool."""
        stub.tool_calls.append((NOT_AD3_TOOL, {}))
        return "dropped"

    stub.app = _RecordingMiddleware(stub.app, stub)
    return stub


@asynccontextmanager
async def running_stub() -> AsyncIterator[tuple[StubMcp, httpx.AsyncClient]]:
    """The stub server, running, and an HTTP client that reaches it in process."""
    stub = build_stub()
    async with (
        stub.server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stub.app), timeout=10
        ) as client,
    ):
        yield stub, client
