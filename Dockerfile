# syntax=docker/dockerfile:1
# ONE image for BOTH Railway services; only the start command differs:
#   api    -> uvicorn main:app ...   (railway.api.toml)
#   worker -> python -m app.worker   (railway.worker.toml)
# Runbook + full env manifest: docs/railway-deploy.md

# Exact-pinned interpreter for reproducible rebuilds. 3.9.23 is the final 3.9
# patch release (the 3.9 line is EOL); bump deliberately, never via a floating
# tag.
FROM python:3.9.23-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1: onnxruntime (u2net matting) links libgomp at runtime; every other
# dependency ships a self-contained manylinux wheel, so no compiler toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. A real writable HOME matters: rembg/pooch download the
# ~176MB u2net weights into U2NET_HOME on the first matte after each deploy
# (deliberately NOT baked into the image -- see requirements.txt). Mount a
# Railway volume at /home/appuser/.u2net to persist them across deploys, or
# uncomment the bake line below to trade +176MB of image for a zero-download
# cold start.
RUN useradd --create-home --uid 10001 appuser
ENV HOME=/home/appuser \
    U2NET_HOME=/home/appuser/.u2net

WORKDIR /app

# Dependency layer, cached until the lock changes. requirements.lock.txt is the
# frozen twin of requirements.txt (regenerate: pip freeze > requirements.lock.txt).
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

# Opt-in alternative to the runtime u2net download (see comment above):
# RUN python -c "from rembg import new_session; new_session('u2net')" \
#     && chown -R appuser:appuser /home/appuser/.u2net

# Application code. --chown because the legacy /outfit-image path writes its
# outputs under the workdir; everything else is env/DB/S3.
COPY --chown=appuser:appuser main.py alembic.ini ./
COPY --chown=appuser:appuser alembic/ alembic/
COPY --chown=appuser:appuser app/ app/
COPY --chown=appuser:appuser scripts/ scripts/

USER appuser

# Default command = the API (the worker service overrides via its Railway
# startCommand). exec so uvicorn is PID 1 and receives SIGTERM directly;
# $PORT is Railway-injected. 1 worker: each worker lazy-loads the ~176MB u2net
# matting model on its first cutout, so >1 worker multiplies that RAM footprint.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
