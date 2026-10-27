# Read-only MCP server ("ask the gallery"), streamable HTTP on 8000.
# Build context: repo root.
FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH
COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --no-create-home app

USER app
EXPOSE 8000
CMD ["python", "-m", "talkback.mcp.server"]
