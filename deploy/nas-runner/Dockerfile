# VDEV-33 — NAS self-hosted runner image: the official GitHub Actions runner plus
# the Docker CLI + buildx (talks to the dind sidecar, never the NAS socket) and the
# tooling our App-auth entrypoint needs (openssl, python3, curl).
FROM ghcr.io/actions/actions-runner:latest

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg openssl python3 && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin && \
    rm -rf /var/lib/apt/lists/*

COPY runner-entrypoint.sh /home/runner/runner-entrypoint.sh
RUN chmod +x /home/runner/runner-entrypoint.sh && chown runner:runner /home/runner/runner-entrypoint.sh

USER runner
WORKDIR /home/runner
ENTRYPOINT ["/home/runner/runner-entrypoint.sh"]
