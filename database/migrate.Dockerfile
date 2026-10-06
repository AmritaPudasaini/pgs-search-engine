# syntax=docker/dockerfile:1
#
# Database migration image: `alembic upgrade head` against DATABASE_URL, then exit.
# Build context: database/ (the db-migrate service of the root docker-compose.yml).
#
# The image also carries the package's idempotent bootstrap scripts and the data they
# load (scripts/seed_*.py, data/), which the separate db-seed task runs once the
# migration has finished, plus scripts/create_admin.py for creating the first admin.
# Each of those runs as its own one-shot container; nothing here is long-running.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim-trixie AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /src
COPY constraints.txt pyproject.toml README.md ./
COPY src ./src
# `auth` (argon2) is what scripts/create_admin.py needs.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --constraint constraints.txt ".[postgres,auth]"

FROM python:${PYTHON_VERSION}-slim-trixie
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv

# Same layout as database/, so alembic.ini (script_location = migrations) and the
# scripts' data paths (<script dir>/../data) resolve exactly as they do locally.
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY data ./data

USER 10001:10001
CMD ["python", "-m", "alembic", "upgrade", "head"]
