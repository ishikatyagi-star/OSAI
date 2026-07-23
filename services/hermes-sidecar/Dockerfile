# Hermes sidecar. Wraps NousResearch/hermes-agent behind a tiny HTTP API.
FROM python:3.12-slim

# git + xz-utils are needed by the hermes install script (clones the repo, unpacks Node).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates bash git xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Hash-lock the wrapper's complete Python dependency graph. Regenerate from
# requirements.in with the compile command recorded in requirements.txt.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.txt

# Install an audited Hermes release. Both the installer bytes and the checkout
# it produces are pinned, so an upstream tag, branch, or redirect cannot change
# a production rebuild without a reviewed repository diff.
ARG HERMES_INSTALL_COMMIT=3ef6bbd201263d354fd83ec55b3c306ded2eb72a
ARG HERMES_INSTALLER_SHA256=c5ba7e89627577fab914514736ecfb3359b66956ca00199bfef616ca35953cb9
RUN curl -fsSL \
      "https://raw.githubusercontent.com/NousResearch/hermes-agent/${HERMES_INSTALL_COMMIT}/scripts/install.sh" \
      -o /tmp/hermes-install.sh \
    && echo "${HERMES_INSTALLER_SHA256}  /tmp/hermes-install.sh" | sha256sum -c - \
    && bash /tmp/hermes-install.sh \
      --skip-setup \
      --skip-browser \
      --commit "${HERMES_INSTALL_COMMIT}" \
    && test "$(git -C /usr/local/lib/hermes-agent rev-parse HEAD)" = "${HERMES_INSTALL_COMMIT}" \
    && rm /tmp/hermes-install.sh
RUN test -x /usr/local/bin/hermes \
    && groupadd --gid 10001 osai \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home \
      --home-dir /home/osai --shell /usr/sbin/nologin osai \
    && mkdir -p /data/hermes \
    && chown -R osai:osai /app /data/hermes /home/osai

COPY --chown=osai:osai main.py /app/main.py
ENV HOME=/home/osai
ENV HERMES_HOME_ROOT=/data/hermes
VOLUME ["/data/hermes"]
EXPOSE 8088
USER 10001:10001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
