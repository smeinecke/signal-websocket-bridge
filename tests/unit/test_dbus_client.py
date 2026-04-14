"""Tests for swb.dbus_client module."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

dbus = pytest.importorskip("dbus")

from swb.config import Config
from swb.dbus_client import (
    _broadcast_to_clients,
    _build_object_path,
    connect_signal_interface,
    get_bus,
    handle_dbus_error,
    is_connected,
    setup_glib_loop,
)


class TestBuildObjectPath:
    """Test object path building."""

    def test_default_path(self):
        """Test default path without account."""
        config = Config(bus="system", host="localhost", port=8765, token=None, account=None, log_level="INFO")
        assert _build_object_path(config) == "/org/asamk/Signal"

    def test_path_with_account(self):
        """Test path with phone number account."""
        config = Config(
            bus="system",
            host="localhost",
            port=8765,
            token=None,
            account="+491234567890",
            log_level="INFO",
        )
        assert _build_object_path(config) == "/org/asamk/Signal/_491234567890"

    def test_path_preserves_other_chars(self):
        """Test that only + is replaced."""
        config = Config(
            bus="system",
            host="localhost",
            port=8765,
            token=None,
            account="+1-555-123-4567",
            log_level="INFO",
        )
        assert _build_object_path(config) == "/org/asamk/Signal/_1-555-123-4567"


class TestGetBus:
    """Test DBus bus selection."""

    def test_system_bus(self):
        """Test system bus selection."""
        config = Config(bus="system", host="localhost", port=8765, token=None, account=None, log_level="INFO")

        with patch("swb.dbus_client.dbus.SystemBus") as mock_system:
            with patch("swb.dbus_client.dbus.SessionBus") as mock_session:
                get_bus(config)
                mock_system.assert_called_once()
                mock_session.assert_not_called()

    def test_session_bus(self):
        """Test session bus selection."""
        config = Config(bus="session", host="localhost", port=8765, token=None, account=None, log_level="INFO")

        with patch("swb.dbus_client.dbus.SystemBus") as mock_system:
            with patch("swb.dbus_client.dbus.SessionBus") as mock_session:
                get_bus(config)
                mock_system.assert_not_called()
                mock_session.assert_called_once()


class TestConnectSignalInterface:
    """Test DBus connection."""

    @pytest.fixture
    def mock_config(self):
        return Config(
            bus="system",
            host="localhost",
            port=8765,
            token=None,
            account=None,
            log_level="INFO",
        )

    @pytest.fixture
    def mock_loop(self):
        return MagicMock()

    @pytest.fixture
    def mock_signal_handler(self):
        return MagicMock()

    def test_successful_connection(self, mock_config, mock_loop, mock_signal_handler):
        """Test successful connection to signal-cli."""
        mock_bus = MagicMock()
        mock_object = MagicMock()
        mock_interface = MagicMock()

        mock_bus.get_object.return_value = mock_object
        mock_interface.version.return_value = "0.12.0"

        connected_clients = set()
        clients_lock = threading.Lock()

        with patch("swb.dbus_client.get_bus", return_value=mock_bus):
            with patch("swb.dbus_client.dbus.Interface", return_value=mock_interface):
                result = connect_signal_interface(
                    mock_config,
                    mock_loop,
                    mock_signal_handler,
                    connected_clients,
                    clients_lock,
                )

        assert result is True
        mock_interface.version.assert_called_once()  # Verify check

    def test_connection_failure(self, mock_config, mock_loop, mock_signal_handler):
        """Test connection failure handling."""
        connected_clients = set()
        clients_lock = threading.Lock()

        with patch("swb.dbus_client.get_bus", side_effect=Exception("DBus error")):
            result = connect_signal_interface(
                mock_config,
                mock_loop,
                mock_signal_handler,
                connected_clients,
                clients_lock,
            )

        assert result is False


class TestHandleDbusError:
    """Test DBus error handling."""

    def test_non_dbus_exception(self):
        """Test non-DBus exceptions are re-raised."""
        exc = ValueError("Not a DBus error")

        with pytest.raises(ValueError):
            handle_dbus_error(exc)

    def test_non_connection_dbus_error(self):
        """Test non-connection DBus errors are re-raised."""
        exc = MagicMock()
        exc.get_dbus_name.return_value = "org.freedesktop.DBus.Error.InvalidArgs"

        with patch("swb.dbus_client.dbus.exceptions.DBusException", type(exc)):
            with pytest.raises(Exception):
                handle_dbus_error(exc)


class TestBroadcastToClients:
    """Test broadcasting to clients."""

    def test_no_clients(self):
        """Test broadcast with no clients doesn't fail."""
        clients = set()
        # Should not raise
        _broadcast_to_clients({"signal": "test"})


class TestIsConnected:
    """Test connection status."""

    def test_initial_state(self):
        """Test initial disconnected state."""
        # Note: This tests the global state, which may be affected by other tests
        # Reset state for clean test
        from swb.dbus_client import _dbus_connected

        assert is_connected() == _dbus_connected


class TestSetupGlibLoop:
    """Test GLib loop setup."""

    def test_setup(self):
        """Test GLib main loop setup."""
        with patch("swb.dbus_client.dbus.mainloop.glib.DBusGMainLoop") as mock_loop:
            setup_glib_loop()
            mock_loop.assert_called_once_with(set_as_default=True)
