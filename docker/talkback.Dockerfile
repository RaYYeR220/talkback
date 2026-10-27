# Talkback service: MAF workflows, HTTP API + SSE, OGraf server.
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

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --no-create-home app

# OGraf graphics packages and renderer pages.
COPY ograf ./ograf
ENV TALKBACK_OGRAF_DIR=/app/ograf \
    TALKBACK_RUN_DIR=/app/runs/md-2031

# The replay matchday is regenerated deterministically from its seed; the recorded broadcast of a real run
# ships next to it, so the gallery is watchable without starting a live run.
RUN python -m talkback.cli matchday --seed 2031 --out /app/runs/md-2031
COPY replays/md-2031.jsonl /app/runs/md-2031/broadcast-replay.jsonl
RUN chown -R app /app/runs

USER app
EXPOSE 8000
CMD ["uvicorn", "talkback.service.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
