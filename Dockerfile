# ── Build stage ────────────────────────────────────────
FROM python:3.12-slim AS builder

# Build deps for any source-built wheels (cryptography / bcrypt fall back to
# source on platforms without manylinux wheels). Currently all listed deps
# ship wheels for linux/amd64 + arm64, but adding these costs ~80MB in the
# builder layer (discarded in the runtime stage) and prevents silent breaks
# the next time we add a native dep.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN mkdir -p app packages \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "."

# ── Runtime stage ─────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ app/
COPY packages/ packages/
COPY design/ design/
COPY scripts/ scripts/

RUN useradd -m orca \
    && mkdir -p /data \
    && chown -R orca:orca /app /data
USER orca

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

ENV PYTHONPATH=/app
CMD ["python", "scripts/start.py"]
