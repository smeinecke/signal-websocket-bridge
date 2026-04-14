"""Tests for swb.config module."""

import os
from unittest.mock import patch

import pytest

from swb.config import Config, load_config


class TestConfig:
    """Test configuration loading."""

    def test_default_values(self):
        """Test default configuration values."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["signalbot"]):
                config = load_config()

        assert config.bus == "system"
        assert config.host == "localhost"
        assert config.port == 8765
        assert config.token is None
        assert config.account is None
        assert config.log_level == "INFO"

    def test_env_variables(self):
        """Test configuration from environment variables."""
        env = {
            "SIGNAL_DBUS_BUS": "session",
            "SIGNAL_WS_HOST": "0.0.0.0",
            "SIGNAL_WS_PORT": "9999",
            "SIGNAL_WS_TOKEN": "secret123",
            "SIGNAL_ACCOUNT": "+491234567890",
            "SIGNAL_LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("sys.argv", ["signalbot"]):
                config = load_config()

        assert config.bus == "session"
        assert config.host == "0.0.0.0"
        assert config.port == 9999
        assert config.token == "secret123"
        assert config.account == "+491234567890"
        assert config.log_level == "DEBUG"

    def test_cli_args_override_env(self):
        """Test CLI arguments override environment variables."""
        env = {
            "SIGNAL_WS_HOST": "env-host",
            "SIGNAL_WS_PORT": "8888",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch(
                "sys.argv",
                [
                    "signalbot",
                    "--host",
                    "cli-host",
                    "--port",
                    "7777",
                    "--token",
                    "cli-token",
                    "--account",
                    "+499999999999",
                    "--log-level",
                    "WARNING",
                ],
            ):
                config = load_config()

        assert config.host == "cli-host"
        assert config.port == 7777
        assert config.token == "cli-token"
        assert config.account == "+499999999999"
        assert config.log_level == "WARNING"

    def test_bus_session_flag(self):
        """Test --session flag sets bus to session."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["signalbot", "--session"]):
                config = load_config()

        assert config.bus == "session"

    def test_bus_system_flag(self):
        """Test --system flag sets bus to system."""
        with patch.dict(os.environ, {"SIGNAL_DBUS_BUS": "session"}, clear=True):
            with patch("sys.argv", ["signalbot", "--system"]):
                config = load_config()

        assert config.bus == "system"
