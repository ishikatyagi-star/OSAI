FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Install deps first (cached layer) using the lockfile for reproducibility.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --locked

COPY . .
EXPOSE 8000

# Default command (compose overrides for the worker): migrate, seed (idempotent,
# non-fatal — skips if data exists; gives free-tier hosts data without shell
# access), then serve.
CMD ["sh", "-c", "uv run alembic upgrade head && (uv run python -m db.seed || echo 'seed skipped') && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000"]
