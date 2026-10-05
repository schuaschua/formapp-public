"""Shared helpers for MCP adapter tests: drive a tool call over the real Streamable HTTP wire
against an in-process ASGI app (Story 4.3), so these tests exercise the same code path a real
MCP client would, not just the domain functions underneath.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from adapters.mcp.server import MCP_PATH

_BASE_URL = "http://testserver"


@asynccontextmanager
async def running_app(app: FastAPI) -> AsyncIterator[FastAPI]:
    """Run the app's ASGI lifespan for the block (starts the MCP session manager's task group,
    the way a real ASGI server such as uvicorn would)."""
    async with LifespanManager(app):
        yield app


async def call_tool(
    app: FastAPI,
    token: str | None,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Open a fresh MCP session against ``app``'s /mcp endpoint with this bearer token (or none,
    for a request with no Authorization header at all), and return the tool's structured result.
    """
    headers = {"authorization": f"Bearer {token}"} if token is not None else {}
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport, base_url=_BASE_URL, headers=headers
    ) as http_client, streamable_http_client(
        f"{_BASE_URL}{MCP_PATH}", http_client=http_client
    ) as (read, write, *_rest), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(name, arguments or {})
    return result.structured_content
