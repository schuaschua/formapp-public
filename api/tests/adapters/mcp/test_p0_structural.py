"""Story 4.3/5.1/5.2 P0: the tool list is exactly the seven fixed tools (spine AD-3), and none of
their input schemas has a parameter that names or could carry a proposal.

No database needed: this introspects the registered tools' schemas, never calls one.
"""

import asyncio
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from adapters.mcp.server import build_mcp_app
from tests.fakes import FakeClock
from tests.support import TEST_SIGNING_KEY

pytestmark = pytest.mark.p0

_EXPECTED_TOOLS = frozenset(
    {
        "get_form_schema",
        "get_draft",
        "patch_draft",
        "validate_draft",
        "get_products",
        "find_customer",
        "link_customer",
    }
)
_ALLOWED_ID_PARAM = "customer_id"
_EXACT_FORBIDDEN = frozenset({"proposal_id", "pid", "draft_id", "id"})


def _is_forbidden(name: str) -> bool:
    if name == _ALLOWED_ID_PARAM:
        return False
    return name in _EXACT_FORBIDDEN or name.endswith("_id")


def _list_tools() -> list[Any]:
    # An engine that is never connected to: the structural check never calls a tool.
    engine = create_async_engine("postgresql+psycopg://unused/unused")
    server, _app = build_mcp_app(engine, SecretStr(TEST_SIGNING_KEY), FakeClock())
    return asyncio.run(server.list_tools())


def test_p0_the_tool_list_is_exactly_the_seven_fixed_tools() -> None:
    tools = _list_tools()

    assert {tool.name for tool in tools} == _EXPECTED_TOOLS


def test_p0_no_tool_takes_a_parameter_that_names_or_could_carry_a_proposal() -> None:
    tools = _list_tools()

    violations = {
        tool.name: bad
        for tool in tools
        if (
            bad := [
                name
                for name in tool.input_schema.get("properties", {})
                if _is_forbidden(name)
            ]
        )
    }

    assert violations == {}


def test_p0_patch_draft_takes_only_answers() -> None:
    tools = {tool.name: tool for tool in _list_tools()}

    assert set(tools["patch_draft"].input_schema["properties"]) == {"answers"}
    assert tools["patch_draft"].input_schema["required"] == ["answers"]


def test_p0_find_customer_takes_only_name_date_of_birth_and_customer_number() -> None:
    """FORM-218: every one of find_customer's search parameters is optional -- the insurance
    agent may give a customer number alone, or any subset of the name/date-of-birth parts
    (spec Boundaries "Always": the AD-3 shape itself never widens)."""
    tools = {tool.name: tool for tool in _list_tools()}

    assert set(tools["find_customer"].input_schema["properties"]) == {
        "first_name",
        "last_name",
        "date_of_birth",
        "customer_number",
    }
    assert set(tools["find_customer"].input_schema.get("required", [])) == set()


def test_p0_link_customer_takes_only_customer_id() -> None:
    tools = {tool.name: tool for tool in _list_tools()}

    assert set(tools["link_customer"].input_schema["properties"]) == {"customer_id"}
    assert tools["link_customer"].input_schema["required"] == ["customer_id"]


def test_p0_the_other_tools_take_no_parameters() -> None:
    tools = {tool.name: tool for tool in _list_tools()}

    for name in _EXPECTED_TOOLS - {"patch_draft", "find_customer", "link_customer"}:
        assert tools[name].input_schema.get("properties", {}) == {}
