# syntax=docker/dockerfile:1

FROM python:3.13-slim-bookworm AS builder

# Pull in the `uv`/`uvx` binaries rather than basing this stage on the uv
# image directly — that image's bundled Python patch version can lag behind
# python:3.13-slim-bookworm's, which made `uv run` in the runtime stage warn
# about a version mismatch against the venv built here.
COPY --from=ghcr.io/astral-sh/uv:python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first, from the lockfile alone, so this layer only
# invalidates when pyproject.toml/uv.lock change — not on every source edit.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Everything the app needs at runtime: application code + migrations.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY README.md ./
COPY pyproject.toml uv.lock ./

# Install the project itself (the `spenza` console script comes from here) —
# the deps layer above is already cached, so this only builds the local package.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# ---------------------------------------------------------------------------

FROM python:3.13-slim-bookworm

# Runtime system libraries for WeasyPrint (PDF report generation), which
# shapes text through Pango/Cairo rather than bundling its own renderer.
# fonts-dejavu-core supplies a glyph for the currency sign ("₹") that
# reports render — Debian's default font set otherwise falls back to tofu.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

RUN groupadd --system --gid 1000 spenza \
    && useradd --system --uid 1000 --gid spenza --no-create-home spenza

WORKDIR /app

COPY --from=builder --chown=spenza:spenza /app /app
# `WORKDIR` created /app as root before the COPY above; --chown only covers
# the copied contents, not that pre-existing directory itself. Without this,
# spenza can't create anything directly under /app — e.g. the `logs/` dir
# structlog creates on startup whenever file logging is enabled (dev/test).
RUN chown spenza:spenza /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv-cache \
    HOME=/app

USER spenza

EXPOSE 8000

# Runs `main_prod()` (gunicorn + uvicorn workers) per src/app.py; override
# the command (e.g. `uv run alembic upgrade head`) for one-off migration runs.
CMD ["uv", "run", "spenza"]
