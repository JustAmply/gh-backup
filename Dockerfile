# syntax=docker/dockerfile:1

FROM python:3.14-slim AS python-builder

ARG TARGETARCH
ARG GITHUB_BACKUP_VERSION=0.61.5

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-compile "github-backup==${GITHUB_BACKUP_VERSION}"

FROM debian:trixie-slim AS binary-fetcher

ARG TARGETARCH
ARG GHORG_VERSION=v1.11.13
ARG SUPERCRONIC_VERSION=v0.2.47

ENV DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH}" in \
        amd64) \
            ghorg_archive="ghorg_${GHORG_VERSION#v}_Linux_x86_64.tar.gz" \
            && ghorg_sha256="8d581ac1fd16392265abea4f3494a1a52fc561c6227ad935593deb052d647302" \
            ;; \
        arm64) \
            ghorg_archive="ghorg_${GHORG_VERSION#v}_Linux_arm64.tar.gz" \
            && ghorg_sha256="ef5229b8a8c39de8f8008f80212e10029cf858aaa4920b793b457963a409c242" \
            ;; \
        *) \
            echo "Unsupported TARGETARCH for ghorg: ${TARGETARCH}" >&2 \
            && exit 1 \
            ;; \
    esac \
    && curl -fsSLO "https://github.com/gabrie30/ghorg/releases/download/${GHORG_VERSION}/${ghorg_archive}" \
    && echo "${ghorg_sha256}  ${ghorg_archive}" | sha256sum -c - \
    && tar -xzf "${ghorg_archive}" ghorg \
    && install -m 0755 ghorg /usr/local/bin/ghorg \
    && rm -f ghorg "${ghorg_archive}"

RUN case "${TARGETARCH}" in \
        amd64) \
            supercronic_bin="supercronic-linux-amd64" \
            && supercronic_sha256="dcb1403c188a9438c47d4bba82a9c357fc9351ce91627fb2bae627f0f5becfc4" \
            ;; \
        arm64) \
            supercronic_bin="supercronic-linux-arm64" \
            && supercronic_sha256="e1124aa34294e2bb8ab7002f347f4363ba35097f3daf4d3c44e9d813c1fb2bb8" \
            ;; \
        *) \
            echo "Unsupported TARGETARCH for supercronic: ${TARGETARCH}" >&2 \
            && exit 1 \
            ;; \
    esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${supercronic_bin}" -o /usr/local/bin/supercronic \
    && echo "${supercronic_sha256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic

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
COPY --link --from=binary-fetcher /usr/local/bin/ghorg /usr/local/bin/supercronic /usr/local/bin/
COPY --link gh_backup /opt/gh-backup/gh_backup
COPY --link --chmod=0755 scripts/entrypoint.sh scripts/run-backup.sh scripts/validate.sh /usr/local/bin/

WORKDIR /app
VOLUME ["/data"]

USER gh-backup

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=2 \
    CMD ["python3", "-m", "gh_backup.health", "health"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["scheduler"]
