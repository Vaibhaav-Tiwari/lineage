FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY lineage ./lineage
COPY config ./config
COPY data ./data
RUN uv sync --frozen --no-dev
ENV PORT=8000
CMD ["sh", "-c", "uv run --no-dev uvicorn lineage.api.main:app --host 0.0.0.0 --port ${PORT}"]
