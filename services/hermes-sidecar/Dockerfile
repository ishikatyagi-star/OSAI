# Hermes sidecar (spike). Wraps NousResearch/hermes-agent behind a tiny HTTP API.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

# Install hermes-agent here. Confirm the exact install per its README, e.g.:
#   RUN pip install hermes-agent
# or clone + `pip install -e .`. Left as a TODO until the spike is validated.

COPY main.py /app/main.py
ENV HERMES_HOME_ROOT=/data/hermes
VOLUME ["/data/hermes"]
EXPOSE 8088
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
