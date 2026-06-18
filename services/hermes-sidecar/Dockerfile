# Hermes sidecar. Wraps NousResearch/hermes-agent behind a tiny HTTP API.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

# Install the hermes CLI (official installer; not on PyPI).
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"

COPY main.py /app/main.py
ENV HERMES_HOME_ROOT=/data/hermes
VOLUME ["/data/hermes"]
EXPOSE 8088
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
