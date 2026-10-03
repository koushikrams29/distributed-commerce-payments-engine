# syntax=docker/dockerfile:1
# Build from the repository root so the shared library is in the build context:
#   docker build -f services/recommendation-service/Dockerfile -t commerce/recommendation-service .

FROM python:3.11-slim-trixie AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# The lock pins every third-party package, the shared library's included, so
# this layer is reused until the lock changes. Its editable `-e ../../libs/common`
# line is for local development; the library is installed from source below.
COPY services/recommendation-service/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    sed '/^-e /d' /tmp/requirements.txt > /tmp/requirements.image.txt \
    && pip install -r /tmp/requirements.image.txt

COPY libs/common /src/libs/common
# --no-deps: everything it needs is already pinned above; pip check fails the
# build if the lock and the library's declared dependencies ever disagree.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps /src/libs/common && pip check


FROM python:3.11-slim-trixie
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8005
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY services/recommendation-service/alembic.ini ./
COPY services/recommendation-service/alembic ./alembic
COPY services/recommendation-service/app ./app
USER app

EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"
# PORT is overridable because hosting platforms (Render, Railway) assign it.
# `exec` makes uvicorn PID 1, so it receives SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\""]
