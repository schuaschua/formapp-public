"""Story 4.2: the agent project's pins, boundaries and image (AD-1, NFR2, NFR23, NFR25)."""

import ast
import re
import tomllib
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
SOURCES = sorted(
    path
    for folder in ("formapp_agent", "evals", "tests")
    for path in (AGENT / folder).rglob("*.py")
)
PYPROJECT = tomllib.loads((AGENT / "pyproject.toml").read_text("utf-8"))
# The api's top-level packages; the agent reaches api only over MCP (AD-1).
API_PACKAGES = {"api", "domain", "adapters", "migrations"}


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_story_4_2_agent_imports_nothing_from_api() -> None:
    assert SOURCES
    offenders = {
        f"{path.relative_to(AGENT)}: {module}"
        for path in SOURCES
        for module in _imported_modules(path)
        if module.split(".")[0] in API_PACKAGES
    }
    assert offenders == set()
    # No path or workspace dependency on the api project either.
    assert "sources" not in PYPROJECT["tool"]["uv"]
    assert "workspace" not in PYPROJECT["tool"]["uv"]


def test_story_4_2_pinned_framework_versions() -> None:
    dependencies = PYPROJECT["project"]["dependencies"]
    assert PYPROJECT["project"]["requires-python"] == "==3.13.*"
    for pin in (
        "agent-framework-foundry==1.13.1",
        "agent-framework-foundry-hosting==1.0.0b260918",
        "mcp==1.30.0",
    ):
        assert pin in dependencies
    # Exact pins only (security.md rule 26).
    for requirement in dependencies + PYPROJECT["dependency-groups"]["dev"]:
        assert re.fullmatch(
            r"[a-z0-9-]+(\[[a-z0-9,-]+\])?==[0-9][0-9a-z.]*", requirement
        )
    assert PYPROJECT["tool"]["uv"]["prerelease"] == "if-necessary-or-explicit"
    assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] == 80


def test_story_4_2_lock_resolves_mcp_below_2() -> None:
    lock = tomllib.loads((AGENT / "uv.lock").read_text("utf-8"))
    versions = {package["name"]: package["version"] for package in lock["package"]}
    assert versions["mcp"] == "1.30.0"
    assert versions["agent-framework-foundry"] == "1.13.1"
    assert versions["agent-framework-foundry-hosting"] == "1.0.0b260918"


def test_story_4_2_environment_read_only_by_settings() -> None:
    offenders = [
        str(path.relative_to(AGENT))
        for path in SOURCES
        if path.parts[-2] != "tests"
        and path.name != "settings.py"
        and re.search(r"\bos\.(environ|getenv)\b", path.read_text("utf-8"))
    ]
    assert offenders == []


def test_story_4_2_no_model_name_in_code() -> None:
    # NFR23: the deployment name reaches the code only as MODEL_DEPLOYMENT_NAME.
    for path in SOURCES:
        if path.parts[-2] == "tests":
            continue
        assert not re.search(r"gpt-|4\.1-mini", path.read_text("utf-8")), path.name


def test_story_4_2_image_is_non_root_without_message_capture() -> None:
    dockerfile = (AGENT / "Dockerfile").read_text("utf-8")
    assert re.search(r"^USER 10001$", dockerfile, re.MULTILINE)
    assert re.search(r"^EXPOSE 8088$", dockerfile, re.MULTILINE)
    assert "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false" in dockerfile
    assert "uv sync --locked --no-dev" in dockerfile
    assert not re.search(r"(?i)(secret|password|connection_string)\s*=", dockerfile)
    ignored = (AGENT / ".dockerignore").read_text("utf-8").splitlines()
    assert "*" in ignored and "!formapp_agent/" in ignored and "!prompts/" in ignored
