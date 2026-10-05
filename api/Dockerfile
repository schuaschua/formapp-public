# formapp api image (Story 1.3): FastAPI on port 8080, the Container App's ingress target port,
# serving the built React app from /app/static (Story 1.4).
# Built from the repository root, because the image needs web/ as well as api/:
# `az acr build --file api/Dockerfile .` (deploy) and `docker build --file api/Dockerfile .` (CI).
# The root .dockerignore allowlists the sources. No secrets: every setting arrives as an environment
# variable from the Container App (spine Consistency Conventions).
# The Alembic scripts are bundled so /readyz can compare the database with this image's head; the
# container never runs them (the pipeline does, AD-10, AD-11).

# Base images pinned by digest (multi-arch indexes): node:22.23.3-bookworm-slim, python:3.13.15-slim,
# uv 0.11.33.
FROM node:22.23.3-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS web
WORKDIR /web
# Exactly the locked dependencies; tools/typescript6 is a local package in the lock file.
COPY web/package.json web/package-lock.json ./
COPY web/tools ./tools
RUN npm ci --no-audit --no-fund
COPY web/index.html web/tsconfig.json web/vite.config.ts web/security-headers.ts ./
COPY web/src ./src
# Type-checks (TypeScript strict) and builds into /web/dist.
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY api/pyproject.toml api/uv.lock ./
# Exactly the locked runtime dependencies; no dev tools in the image.
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
# The system CA bundle verifies PostgreSQL's certificate (sslmode=verify-full, sslrootcert = that
# bundle's path); the build fails if the base image ever drops it.
RUN test -s /etc/ssl/certs/ca-certificates.crt \
    && groupadd --system --gid 10001 formapp \
    && useradd --system --uid 10001 --gid formapp --no-create-home --shell /usr/sbin/nologin formapp
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY api/alembic.ini ./
COPY api/migrations ./migrations
COPY api/domain ./domain
COPY api/adapters ./adapters
# Story 7.1: the nightly feedback job (`python -m jobs.feedback`), the same image as the api
# container, just with a different Container Apps command (AD-20).
COPY api/jobs ./jobs
# Story 1.7: the released form schemas (AD-7) at /form-schema/, where domain/schema.py looks (two
# levels above domain/). Only v<N>.json files: the lint and its fixtures stay out of the image.
COPY form-schema/v*.json /form-schema/
# The settings default FORMAPP_STATIC_DIR is /app/static.
COPY --from=web /web/dist ./static
# DATABASE_SSLROOTCERT names the CA bundle file explicitly for libpq (the OpenSSL bundled in the
# psycopg wheel doesn't reliably find the system store); SSL_CERT_FILE covers other OpenSSL users.
ENV PATH="/app/.venv/bin:${PATH}" \
    DATABASE_SSLROOTCERT=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001
EXPOSE 8080
# Behind Container Apps ingress: trust its X-Forwarded-* headers. No access log: requests are recorded
# as request spans in Application Insights, and every log line is structured JSON (Story 1.5).
CMD ["uvicorn", "adapters.rest.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log", "--no-server-header"]
