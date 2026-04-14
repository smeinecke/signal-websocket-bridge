# Multi-stage build for signal-websocket-bridge
# Standard Debian with OpenJDK for maximum compatibility

# Stage 1: Build environment
FROM python:3.13-slim-trixie AS builder

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install the package using uv
RUN uv sync --frozen --no-dev \
    && uv pip install .

# Stage 2: Runtime with signal-cli
FROM python:3.13-slim-trixie AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # dbus and glib for signal-cli
    libdbus-1-3 \
    libgirepository-1.0-1 \
    dbus \
    # curl for downloading signal-cli
    curl \
    unzip \
    # OpenJDK for signal-cli
    default-jre-headless \
    # supervisor for process management
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Download and install signal-cli
ARG SIGNAL_CLI_VERSION=0.14.2
RUN curl -fsSL -o /tmp/signal-cli.tar.gz \
    "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz" \
    && tar -xzf /tmp/signal-cli.tar.gz -C /opt \
    && ln -sf "/opt/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli" /usr/local/bin/signal-cli \
    && rm /tmp/signal-cli.tar.gz

# Copy uv and venv from builder
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app/.venv /app/.venv

# Copy supervisor configuration
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create non-root user for running services
RUN groupadd -r signal && useradd -r -g signal signal \
    && mkdir -p /var/lib/signal-cli /var/lib/swb \
    && chown -R signal:signal /var/lib/signal-cli /var/lib/swb

# Expose WebSocket port
EXPOSE 8765

# Environment variables
ENV SIGNAL_WS_HOST=0.0.0.0 \
    SIGNAL_WS_PORT=8765 \
    SIGNAL_DBUS_BUS=system \
    SIGNAL_LOG_LEVEL=INFO \
    PATH="/app/.venv/bin:${PATH}"

# Start supervisor to manage both processes
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
