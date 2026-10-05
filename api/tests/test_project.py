"""Story 1.3: project layout, exact pins, lint settings and the container image."""

import json
import re
import tomllib

from tests.support import API_ROOT

PYPROJECT = tomllib.loads((API_ROOT / "pyproject.toml").read_text())
DOCKERFILE = (API_ROOT / "Dockerfile").read_text()


def test_story_1_3_hexagonal_layout() -> None:
    for folder in (
        "domain",
        "adapters/rest",
        "adapters/mcp",
        "adapters/chat",
        "adapters/db",
        "migrations",
    ):
        assert (API_ROOT / folder).is_dir(), folder


def test_story_1_3_stack_versions_are_pinned_exactly() -> None:
    pins: dict[str, str] = {}
    for dependency in PYPROJECT["project"]["dependencies"]:
        match = re.fullmatch(r"([a-z0-9-]+)(?:\[[a-z,]+\])?==(.+)", dependency)
        assert match, f"{dependency} must be pinned with =="
        pins[match[1]] = match[2]

    assert PYPROJECT["project"]["requires-python"] == "==3.13.*"
    assert {
        name: pins[name]
        for name in (
            "fastapi",
            "uvicorn",
            "pydantic",
            "sqlalchemy",
            "psycopg",
            "alembic",
        )
    } == {
        "fastapi": "0.141.1",
        "uvicorn": "0.53.0",
        "pydantic": "2.13.5",
        "sqlalchemy": "2.0.54",
        "psycopg": "3.3.6",
        "alembic": "1.20.0",
    }
    # Story 1.7: the domain validates with jsonschema (spine Stack).
    assert pins["jsonschema"] == "4.26.0"
    assert all(
        "==" in dependency for dependency in PYPROJECT["dependency-groups"]["dev"]
    )
    assert (API_ROOT / "uv.lock").is_file()


def test_story_1_3_lint_and_type_settings_follow_coding_style() -> None:
    assert set(PYPROJECT["tool"]["ruff"]["lint"]["extend-select"]) == {
        "I",
        "B",
        "UP",
        "S",
    }
    overrides = PYPROJECT["tool"]["mypy"]["overrides"]
    assert any(
        o["module"] == ["domain", "domain.*"] and o["strict"] is True for o in overrides
    )


def _instructions() -> list[str]:
    """Dockerfile instructions with comments dropped and continuation lines joined."""
    joined = re.sub(r"\\\n\s*", " ", DOCKERFILE)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_story_1_3_image_runs_non_root_on_8080_without_migrating() -> None:
    instructions = _instructions()
    last_from = max(
        i for i, line in enumerate(instructions) if line.startswith("FROM ")
    )
    final_stage = instructions[last_from:]
    users = [line.split()[1] for line in final_stage if line.startswith("USER ")]
    command = json.loads(
        next(line for line in final_stage if line.startswith("CMD "))[4:]
    )

    assert users and users[-1] not in ("root", "0")
    assert "EXPOSE 8080" in final_stage
    assert command[:3] == ["uvicorn", "adapters.rest.app:create_app", "--factory"]
    assert command[command.index("--port") + 1] == "8080"
    # Behind Container Apps ingress, and no plain-text access log (Story 1.5 logs).
    assert "--proxy-headers" in command
    assert command[command.index("--forwarded-allow-ips") + 1] == "*"
    assert "--no-access-log" in command
    assert not any("alembic" in part for part in command)
    assert re.search(
        r"^FROM python:3\.13[^@\s]*@sha256:[0-9a-f]{64}", DOCKERFILE, re.MULTILINE
    )


def test_story_1_3_image_verifies_tls_with_the_system_ca_bundle() -> None:
    instructions = _instructions()

    assert any("test -s /etc/ssl/certs/ca-certificates.crt" in i for i in instructions)
    assert any(
        "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in i for i in instructions
    )


def test_story_1_3_coverage_minimum_is_80_percent() -> None:
    assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] == 80


def test_story_1_3_image_bundles_the_migrations_but_no_secrets() -> None:
    assert re.search(r"COPY .*alembic\.ini", DOCKERFILE)
    assert re.search(r"COPY .*migrations", DOCKERFILE)
    assert not re.search(
        r"^\s*(ENV|ARG)\s+\S*(PASSWORD|SECRET|KEY|TOKEN)",
        DOCKERFILE,
        re.MULTILINE | re.IGNORECASE,
    )


def test_story_1_4_dockerignore_is_an_allowlist_without_secrets() -> None:
    # The build context is the repo root, so the root .dockerignore must start by excluding
    # everything (`*`) and allowlist sources after it; env files and virtualenvs stay out even
    # inside allowlisted folders.
    lines = [
        line.strip()
        for line in (API_ROOT.parent / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines[0] == "*"
    for pattern in ("**/.env", "**/.env.*", "**/.venv"):
        assert pattern in lines, pattern


def test_story_1_3_the_app_never_runs_migrations() -> None:
    for path in (API_ROOT / "adapters").rglob("*.py"):
        source = path.read_text()
        assert (
            "alembic.command" not in source
            and "from alembic import command" not in source
        ), path
        assert "upgrade(" not in source, path


def test_story_1_7_image_ships_only_the_released_form_schemas() -> None:
    # domain/schema.py finds them two levels above domain/: /form-schema/ in the image.
    assert "COPY form-schema/v*.json /form-schema/" in _instructions()
    lines = [
        line.strip()
        for line in (API_ROOT.parent / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    form_schema = [line for line in lines if "form-schema" in line]
    assert form_schema == ["!form-schema/v*.json"]
