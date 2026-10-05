"""Story 1.3: api/domain imports no adapter, framework, database or HTTP code (spine AD-2)."""

from textwrap import dedent

from tests.domain.source_rules import domain_sources, forbidden_imports, module_name


def test_story_1_3_domain_imports_no_adapter_or_framework_code() -> None:
    violations = {
        str(path.name): found
        for path, source in domain_sources()
        if (
            found := forbidden_imports(
                source, module_name(path), is_package=path.name == "__init__.py"
            )
        )
    }

    assert violations == {}


def test_story_1_3_import_rule_catches_violations() -> None:
    source = dedent(
        """\
        import fastapi
        from sqlalchemy import text
        from adapters.db import engine
        import mcp.server
        from ..adapters import settings
        from . import errors
        from datetime import datetime
        """
    )

    assert sorted(forbidden_imports(source, "domain.drafts")) == [
        "adapters",
        "adapters.db",
        "fastapi",
        "mcp.server",
        "sqlalchemy",
    ]


def test_story_1_3_import_rule_covers_httpx2() -> None:
    assert forbidden_imports("import httpx2\nfrom httpx2 import Client") == [
        "httpx2",
        "httpx2",
    ]


def test_story_1_3_import_rule_resolves_relative_imports_in_a_package_init() -> None:
    # In domain/__init__.py, "." is domain itself and ".." is the top level.
    source = "from .errors import DomainError\nfrom ..adapters import settings\n"

    assert forbidden_imports(source, "domain", is_package=True) == ["adapters"]
    # In a sub-package's __init__.py, ".." is domain.
    assert (
        forbidden_imports(
            "from ..clock import Clock\n", "domain.rules", is_package=True
        )
        == []
    )
