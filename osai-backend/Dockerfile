FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml README.md ./
RUN uv sync --no-dev
COPY . .

EXPOSE 8000
