# Multi-stage build with self-managed signal-cli install.
# Uses upstream release archives so all target platforms are valid images.

# Stage 1: Shared runtime base (install once, reused by builder + final)
FROM debian:testing-slim AS runtime-base

USER root
WORKDIR /app

# Resolved in CI from the latest upstream release; defaults to latest for local builds.
ARG SIGNAL_CLI_VERSION=latest

# Install Python runtime, Java (required by signal-cli), and required system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-dbus \
    python3-gi \
    libcairo2 \
    libgirepository-1.0-1 \
    libgirepository-2.0-0 \
    libglib2.0-0t64 \
    libdbus-1-3 \
    dbus-daemon \
    default-jre-headless \
    ca-certificates \
    tar \
    curl \
    supervisor \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install signal-cli from upstream Java distribution (works across CPU architectures).
RUN set -eux; \
    if [ "$SIGNAL_CLI_VERSION" = "latest" ]; then \
        SIGNAL_CLI_VERSION="$( \
            curl -fsSL https://api.github.com/repos/AsamK/signal-cli/releases/latest \
            | sed -n 's/.*"tag_name": "v\([^"]*\)".*/\1/p' \
            | head -n1 \
        )"; \
    fi; \
    test -n "$SIGNAL_CLI_VERSION"; \
    curl -fsSL "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz" -o /tmp/signal-cli.tar.gz; \
    tar -xzf /tmp/signal-cli.tar.gz -C /opt; \
    mv "/opt/signal-cli-${SIGNAL_CLI_VERSION}" /opt/signal-cli; \
    ln -sf /opt/signal-cli/bin/signal-cli /usr/bin/signal-cli; \
    rm -f /tmp/signal-cli.tar.gz

# Runtime filesystem compatibility
RUN mkdir -p /var/lib/signal-cli /var/lib/swb \
    && mkdir -p /run/dbus \
    && mkdir -p /usr/local/bin \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/local/bin/python

# Stage 2: Build environment
FROM runtime-base AS builder

WORKDIR /app

# Install build dependencies for dbus-python.
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

# Use supervisord to run dbus + signal-cli + bridge
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
