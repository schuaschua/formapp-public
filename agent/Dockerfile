# formapp agent image (Story 4.2): the Foundry hosted agent, serving POST /responses and
# GET /readiness on port 8088 (the hosted-agent default; PORT overrides it).
# Build context is agent/: `docker build agent/` (CI), and later `az acr build` in the deploy
# (Story 4.1). The .dockerignore next to this file allowlists the sources. No secrets: every
# setting arrives as an environment variable from the platform (spine Consistency Conventions).

# Base images pinned by digest (multi-arch indexes), the same as api/: python:3.13.15-slim,
# uv 0.11.33.
FROM ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 AS uv

FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Exactly the locked runtime dependencies (the pre-release pins included); no dev tools.
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
RUN groupadd --system --gid 10001 formapp \
    && useradd --system --uid 10001 --gid formapp --no-create-home --shell /usr/sbin/nologin formapp
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY formapp_agent ./formapp_agent
COPY prompts ./prompts
# Message capture stays off even for code that reads this variable directly (security.md rule 2);
# the agent's own telemetry setup forces it off as well. The hosting package keeps its on-disk
# state under ~/.agentserver by default, and uid 10001 has no home directory.
ENV PATH="/app/.venv/bin:${PATH}" \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false \
    AGENTSERVER_STATE_ROOT=/tmp/agentserver \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001
EXPOSE 8088
CMD ["python", "-m", "formapp_agent.main"]
