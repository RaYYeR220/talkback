# Archivist hosted agent (Foundry Agent Service, linux/amd64, port 8088).
# Build context: repo root (azure.yaml sets docker.context: ../..).
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
COPY agents/requirements.txt ./agents-requirements.txt
RUN uv pip install --python /app/.venv/bin/python -r agents-requirements.txt

COPY README.md LICENSE ./
COPY src ./src
# --inexact keeps the hosting packages installed above.
RUN uv sync --frozen --no-dev --no-editable --inexact

COPY agents/common/hosting.py agents/archivist/main.py ./
# Scale-to-zero agents pay cold starts; precompile the stdlib once at build time.
RUN python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')" || true; \
    python -m compileall -q hosting.py main.py

EXPOSE 8088
CMD ["python", "main.py"]
