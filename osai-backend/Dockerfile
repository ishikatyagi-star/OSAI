FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Install deps first (cached layer) using the lockfile for reproducibility.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --locked

COPY . .

# Drop root: run the app as an unprivileged user so a process compromise can't
# write the image or escalate on the host. The build context (.dockerignore)
# already excludes .env/.git/tests from the image.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Render uses this default; Compose overrides it with explicit migrate/API/worker
# commands. Production startup migrates the schema but never loads demo seed data.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn api.main:app --no-proxy-headers --host 0.0.0.0 --port 8000"]
