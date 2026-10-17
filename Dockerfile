# The Lineage API for a hosted deployment (graph-only: no LLM, no API keys).
# The company graph comes baked into the FalkorDB image (deploy/falkordb), so the raw cache is not shipped.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy FASTEMBED_CACHE_PATH=/app/.fastembed \
    LLM_BACKEND=graph-only PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY lineage ./lineage
COPY config ./config
RUN uv sync --frozen --no-dev
# fetch the embedding model at build time, so the running service needs no outbound access
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
CMD ["python", "-m", "lineage.deploy"]
