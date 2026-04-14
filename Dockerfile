# Multi-stage build using official signal-cli native image
# signal-cli native uses GraalVM native image (no Java runtime needed)

# Stage 1: Shared runtime base (install once, reused by builder + final)
FROM ghcr.io/asamk/signal-cli:latest-native AS runtime-base

USER root
WORKDIR /app

# Install Python runtime and required system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-dbus \
    python3-gi \
    libcairo2 \
    libgirepository-1.0-1 \
    libgirepository-2.0-0 \
    libglib2.0-0 \
    libdbus-1-3 \
    dbus-daemon \
    curl \
    supervisor \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Runtime filesystem compatibility
RUN mkdir -p /var/lib/signal-cli /var/lib/swb \
    && mkdir -p /run/dbus \
    && mkdir -p /usr/local/bin \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/local/bin/python

# Stage 2: Build environment
FROM runtime-base AS builder

WORKDIR /app

# Install build dependencies for dbus-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    pkg-config \
    libdbus-1-dev \
    libglib2.0-dev \
    libcairo2-dev \
    libgirepository-2.0-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir --break-system-packages uv

# Copy dependency metadata first for better layer caching
COPY pyproject.toml uv.lock ./

# Install only third-party deps first (stable cache layer)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project separately (fast when only app code changes)
COPY src/ ./src/
RUN uv pip install --no-deps .

# Stage 3: Final runtime image
FROM runtime-base AS runtime

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy supervisor configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create data directories
# Expose WebSocket / HTTP port
EXPOSE 8765

# Environment variables
ENV SIGNAL_WS_HOST=0.0.0.0 \
    SIGNAL_WS_PORT=8765 \
    SIGNAL_DBUS_BUS=session \
    SIGNAL_LOG_LEVEL=INFO \
    SIGNAL_WS_TOKEN="" \
    SIGNAL_ACCOUNT="" \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/usr/lib/python3/dist-packages"

# Liveness / readiness probe via the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SIGNAL_WS_PORT}/health || exit 1

# Reset entrypoint from signal-cli image and use supervisord
ENTRYPOINT []
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
