"""Configuration and argument parsing for signalbot."""

import argparse
import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Application configuration."""

    bus: str  # "system" or "session"
    host: str
    port: int
    token: str | None
    account: str | None
    log_level: str
    buffer_size: int  # max events to buffer for replay; 0 = disabled


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="signal-cli DBus ↔ WebSocket bridge")
    bus_group = parser.add_mutually_exclusive_group()
    bus_group.add_argument(
        "--system",
        dest="bus",
        action="store_const",
        const="system",
        help="Connect to the system bus (default, or SIGNAL_DBUS_BUS=system)",
    )
    bus_group.add_argument(
        "--session",
        dest="bus",
        action="store_const",
        const="session",
        help="Connect to the session bus (or SIGNAL_DBUS_BUS=session)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SIGNAL_WS_HOST", "localhost"),
        help="WebSocket listen host (env: SIGNAL_WS_HOST, default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SIGNAL_WS_PORT", "8765")),
        help="WebSocket listen port (env: SIGNAL_WS_PORT, default: 8765)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SIGNAL_WS_TOKEN"),
        help="WebSocket auth token required for connections (env: SIGNAL_WS_TOKEN)",
    )
    parser.add_argument(
        "--account",
        default=os.environ.get("SIGNAL_ACCOUNT"),
        help="Account phone number for multi-account mode (env: SIGNAL_ACCOUNT, e.g. +4915...)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("SIGNAL_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (env: SIGNAL_LOG_LEVEL, default: INFO)",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=int(os.environ.get("SIGNAL_BUFFER_SIZE", "0")),
        help="Number of signal events to buffer for replay on client reconnect (env: SIGNAL_BUFFER_SIZE, default: 0 = disabled)",
    )
    return parser.parse_args()


def load_config() -> Config:
    """Load configuration from CLI args and environment."""
    args = _parse_args()

    bus = args.bus if args.bus else os.environ.get("SIGNAL_DBUS_BUS", "system")

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    return Config(
        bus=bus,
        host=args.host,
        port=args.port,
        token=args.token,
        account=args.account,
        log_level=args.log_level,
        buffer_size=max(0, args.buffer_size),
    )
