# syntax=docker/dockerfile:1
FROM --platform=linux/amd64 docker.io/library/python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS builder

WORKDIR /build
COPY requirements/build.lock requirements/portable.lock ./requirements/
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/build.lock \
    && python -m pip install --no-cache-dir --require-hashes --prefix=/runtime -r requirements/portable.lock

ENV SOURCE_DATE_EPOCH=0
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src ./src
RUN python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels . \
    && python -m pip install --no-cache-dir --no-deps --prefix=/runtime /wheels/aioa_nonzero_cloudops_agent-*.whl \
    && PYTHONPATH=/runtime/lib/python3.12/site-packages python -m pip check

FROM --platform=linux/amd64 docker.io/library/python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS runtime

ARG APPLICATION_VERSION=0.2.0rc1
ARG SOURCE_COMMIT=unknown

LABEL org.opencontainers.image.title="AIOA Non-Zero CloudOps Agent" \
      org.opencontainers.image.version="${APPLICATION_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.licenses="MIT"

ENV APPLICATION_VERSION="${APPLICATION_VERSION}" \
    SOURCE_COMMIT="${SOURCE_COMMIT}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIOA_RUNTIME_MODE=portable \
    AIOA_MODEL_PROVIDER=mock \
    AIOA_AWS_INTEGRATION_ENABLED=false \
    AIOA_HOST=0.0.0.0 \
    AIOA_PORT=8765 \
    AIOA_ALLOWED_ORIGINS=same-origin \
    AIOA_ALLOWED_EGRESS=none \
    AIOA_STORAGE_MODE=file \
    AIOA_LOCAL_MODE=mock \
    AIOA_LOCAL_HITL_STATE_PATH=/var/lib/aioa/durable-truth.json \
    AIOA_LOCAL_INVENTORY_PATH=/var/lib/aioa/mock-inventory.json \
    AIOA_LOCAL_API_TOKEN_PATH=/var/lib/aioa/operator.token \
    AIOA_SESSION_TTL_SECONDS=600 \
    AIOA_REQUEST_TIMEOUT_SECONDS=10 \
    AIOA_PROVIDER_TIMEOUT_SECONDS=0 \
    AIOA_RETRY_BUDGET=0 \
    AIOA_REQUEST_SIZE_LIMIT_BYTES=16384 \
    AIOA_LOG_LEVEL=INFO \
    AIOA_PUBLIC_MODE_LABEL=DEMO_SANDBOX \
    AIOA_SANDBOX_MODE=MOCK_OFFLINE \
    AIOA_AUTHORITY_MODE=HUMAN_APPROVAL_REQUIRED

COPY --from=builder /runtime/ /usr/local/
RUN groupadd --gid 65532 aioa \
    && useradd --uid 65532 --gid 65532 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin aioa \
    && usermod --append --groups root aioa \
    && mkdir -p /app /var/lib/aioa \
    && chmod 2770 /var/lib/aioa

WORKDIR /app
USER aioa
EXPOSE 8765
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import os,urllib.request; response=urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"AIOA_PORT\"]}/health',timeout=2); raise SystemExit(0 if response.status==200 else 1)"]
ENTRYPOINT ["python", "-m", "aioa_cloudops_agent.portable_server"]
