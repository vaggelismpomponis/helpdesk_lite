# ==============================================================================
# HelpDesk Lite - Multi-stage Application Dockerfile (Chainlit + LangGraph)
# Pinned Base Image Policy: python:3.11-slim (docs/PINNED_VERSIONS.md)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Minimal runtime dependencies for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create non-root system user and group for enhanced container security
RUN groupadd -g 1001 appuser && \
    useradd -u 1001 -g appuser -s /bin/bash -m appuser

# Pre-create writable config directories for Chainlit runtime
RUN mkdir -p /app/.chainlit && chown -R appuser:appuser /app

# Copy application source code
COPY src/ /app/src/

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Periodic healthcheck querying the Chainlit root UI endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Start the Chainlit application headless on port 8000
CMD ["chainlit", "run", "src/app.py", "--host", "0.0.0.0", "--port", "8000", "--headless"]
