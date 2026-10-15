# FinAgent platform image shared by the API, worker, scheduler and MCP server.
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

WORKDIR /build
RUN uv venv /opt/venv
# Dependencies first (only the version files are needed), so source edits reuse this layer.
COPY pyproject.toml README.md ./
COPY tradingagents/__init__.py tradingagents/__init__.py
COPY finagent/__init__.py finagent/__init__.py
RUN mkdir -p cli && touch cli/__init__.py \
 && uv pip install --python /opt/venv/bin/python ".[platform]"
COPY tradingagents tradingagents
COPY cli cli
COPY finagent finagent
RUN uv pip install --python /opt/venv/bin/python --no-deps --reinstall-package fin-agent .

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 app \
 && install -d -m 0755 -o app -g app /data /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app finagent/db/migrations finagent/db/migrations
COPY --chown=app:app skills skills
USER app

EXPOSE 8000 8001
CMD ["uvicorn", "finagent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
