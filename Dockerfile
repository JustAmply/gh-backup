# syntax=docker/dockerfile:1

FROM python:3.14-slim AS python-builder

ARG TARGETARCH
ARG GITHUB_BACKUP_VERSION=0.61.5

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-compile "github-backup==${GITHUB_BACKUP_VERSION}"

FROM golang:1.26.5-bookworm AS go-tools-builder

ARG GHORG_VERSION=v1.11.13
ARG SUPERCRONIC_VERSION=v0.2.47

ENV CGO_ENABLED=0
ENV GOTOOLCHAIN=local

RUN go install "github.com/gabrie30/ghorg@${GHORG_VERSION}" \
    && go install -ldflags "-X main.Version=${SUPERCRONIC_VERSION}" \
    "github.com/aptible/supercronic@${SUPERCRONIC_VERSION}"

FROM python:3.14-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONPATH="/opt/gh-backup"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        git \
        git-lfs \
        restic \
        tzdata \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /data/logs /data/metadata /data/mirrors /data/state

RUN groupadd --gid 10001 gh-backup \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/gh-backup --shell /usr/sbin/nologin gh-backup \
    && chown -R gh-backup:gh-backup /app /data

COPY --link --from=python-builder /opt/venv /opt/venv
COPY --link --from=go-tools-builder /go/bin/ghorg /go/bin/supercronic /usr/local/bin/
COPY --link gh_backup /opt/gh-backup/gh_backup
COPY --link --chmod=0755 scripts/entrypoint.sh scripts/run-backup.sh scripts/validate.sh /usr/local/bin/

WORKDIR /app
VOLUME ["/data"]

USER gh-backup

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=2 \
    CMD ["python3", "-m", "gh_backup.health", "health"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["scheduler"]
