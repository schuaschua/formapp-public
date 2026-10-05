"""Static checks over api/domain source (spine AD-2, AD-18), shared by the rule tests."""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "domain"

# AD-2 and coding-style.md rule 9: the domain imports no framework, database, HTTP or adapter code.
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "adapters",
        "aiohttp",
        "alembic",
        "azure",
        "fastapi",
        "httpx",
        "httpx2",
        "mcp",
        "psycopg",
        "psycopg2",
        "pydantic_settings",
        "requests",
        "sqlalchemy",
        "starlette",
        "urllib3",
        "uvicorn",
    }
)

# AD-18: the system clock, reached as datetime.now(), date.today(), time.time() and friends.
_CLOCK_ATTRIBUTES = {
    "datetime": {"now", "utcnow", "today"},
    "date": {"today"},
    "time": {"time", "time_ns", "localtime", "gmtime"},
}
_CLOCK_FROM_IMPORTS = {"time": {"time", "time_ns", "localtime", "gmtime"}}
# SQL that reads the database clock instead of taking the time as a parameter.
_SQL_CLOCK = re.compile(
    r"\b(now|clock_timestamp|statement_timestamp|transaction_timestamp)\s*\(\s*\)"
    r"|\b(current_timestamp|current_date|current_time|localtimestamp|localtime)\b",
    re.IGNORECASE,
)


def domain_sources() -> Iterator[tuple[Path, str]]:
    for path in sorted(DOMAIN_DIR.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def module_name(path: Path) -> str:
    relative = path.relative_to(DOMAIN_DIR.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def forbidden_imports(
    source: str, module: str = "domain.module", is_package: bool = False
) -> list[str]:
    """Return the forbidden modules that source imports.

    module is the importing module's dotted name; is_package says it is a package's __init__.py,
    whose relative imports start from the package itself rather than its parent.
    """
    parts = module.split(".")
    package = parts if is_package else parts[:-1]
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Resolve a relative import against the importing module's package.
                start = package[: len(package) - (node.level - 1)]
                base = ".".join([*start, node.module or ""]).strip(".")
                names = (
                    [base] if node.module else [f"{base}.{a.name}" for a in node.names]
                )
            else:
                names = [node.module or ""]
        else:
            continue
        found += [
            name for name in names if name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS
        ]
    return found


def _clock_aliases(tree: ast.AST) -> dict[str, str]:
    """Local names bound to the datetime/time modules or the datetime/date classes."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("datetime", "time") and alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for alias in node.names:
                if alias.name in ("datetime", "date") and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def system_clock_calls(source: str) -> list[str]:
    """Return the system-clock calls and SQL clock functions that source uses."""
    found = []
    tree = ast.parse(source)
    # Bare string statements (docstrings) are prose, never SQL that runs.
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    aliases = _clock_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            # now() on datetime/date/time, or on an alias of them (import time as t).
            owner = aliases.get(node.value.id, node.value.id)
            if node.attr in _CLOCK_ATTRIBUTES.get(owner, set()):
                found.append(f"{owner}.{node.attr}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            # datetime.datetime.now(), or dt.datetime.now() after import datetime as dt
            if node.attr in _CLOCK_ATTRIBUTES.get(node.value.attr, set()):
                found.append(f"{node.value.attr}.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module in _CLOCK_FROM_IMPORTS:
            for alias in node.names:
                if alias.name in _CLOCK_FROM_IMPORTS[node.module]:
                    found.append(f"from {node.module} import {alias.name}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
        ):
            match = _SQL_CLOCK.search(node.value)
            if match:
                found.append(f"SQL {match.group(0)}")
    return found
