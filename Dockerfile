FROM python:3.12-slim

ARG TARGETARCH
ARG GHORG_VERSION=v1.11.10
ARG GITHUB_BACKUP_VERSION=0.61.5
ARG SUPERCRONIC_VERSION=v0.2.43

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        git-lfs \
        tzdata \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "github-backup==${GITHUB_BACKUP_VERSION}"

RUN case "${TARGETARCH}" in \
        amd64) \
            ghorg_archive="ghorg_${GHORG_VERSION#v}_Linux_x86_64.tar.gz" \
            && ghorg_sha256="28ccf93b5a320ec31589e1b84d3e58fc5661fbbeb1b6e892ca59346790c96850" \
            ;; \
        arm64) \
            ghorg_archive="ghorg_${GHORG_VERSION#v}_Linux_arm64.tar.gz" \
            && ghorg_sha256="ad807fa207a85a1ba373a25509d0c33a7ce6ac7bc4adb8d094f19df142a40f0f" \
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
            && supercronic_sha1="f97b92132b61a8f827c3faf67106dc0e4467ccf2" \
            ;; \
        arm64) \
            supercronic_bin="supercronic-linux-arm64" \
            && supercronic_sha1="5c6266786c2813d6f8a99965d84452faae42b483" \
            ;; \
        *) \
            echo "Unsupported TARGETARCH for supercronic: ${TARGETARCH}" >&2 \
            && exit 1 \
            ;; \
    esac \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${supercronic_bin}" -o /usr/local/bin/supercronic \
    && echo "${supercronic_sha1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

RUN mkdir -p /app /data/logs /data/metadata /data/mirrors /data/state /run/secrets

COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY scripts/run-backup.sh /usr/local/bin/run-backup.sh
COPY scripts/validate.sh /usr/local/bin/validate.sh

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/run-backup.sh /usr/local/bin/validate.sh

WORKDIR /app
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["scheduler"]
