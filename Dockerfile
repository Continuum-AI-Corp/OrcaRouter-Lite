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

# Install the runtime dependencies only, read straight out of pyproject. The
# project itself is deliberately NOT installed here — the runtime stage puts
# the source on PYTHONPATH instead — so this layer is invalidated only when
# the dependency list changes, never on a code or README edit.
RUN pip install --no-cache-dir --upgrade pip \
    && python -c 'import tomllib;f=open("pyproject.toml","rb");print(*tomllib.load(f)["project"]["dependencies"],sep=chr(10))' > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# ── Runtime stage ─────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="OrcaRouter Lite" \
      org.opencontainers.image.description="Self-hosted LLM router with a managed safety net. OpenAI-compatible, BYOK." \
      org.opencontainers.image.source="https://github.com/Continuum-AI-Corp/OrcaRouter-Lite" \
      org.opencontainers.image.licenses="MIT"

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
