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
        # Empty list → _autodiscover_object_path returns root path →
        # per-account listAccounts() verification is skipped.
        mock_interface.listAccounts.return_value = []

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
        mock_interface.listAccounts.assert_called()  # Verify mode detection probe

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


class TestGetInterface:
    """Test get_interface function."""

    def test_get_interface_raises_when_not_connected(self):
        """Test get_interface raises when not connected."""
        # Reset global state
        import swb.dbus_client as dc
        from swb.dbus_client import _signal_interface, get_interface

        original = dc._signal_interface
        dc._signal_interface = None

        try:
            with pytest.raises(RuntimeError, match="DBus interface not connected"):
                get_interface()
        finally:
            dc._signal_interface = original


class TestGetObjectInstance:
    """Test get_object_instance function."""

    def test_get_object_instance_raises_when_not_connected(self):
        """Test get_object_instance raises when not connected."""
        # Reset global state
        import swb.dbus_client as dc
        from swb.dbus_client import _signal_object, get_object_instance

        original = dc._signal_object
        dc._signal_object = None

        try:
            with pytest.raises(RuntimeError, match="DBus object not connected"):
                get_object_instance()
        finally:
            dc._signal_object = original


class TestGetBusInstance:
    """Test get_bus_instance function."""

    def test_get_bus_instance_raises_when_not_connected(self):
        """Test get_bus_instance raises when not connected."""
        # Reset global state
        import swb.dbus_client as dc
        from swb.dbus_client import _bus, get_bus_instance

        original = dc._bus
        dc._bus = None

        try:
            with pytest.raises(RuntimeError, match="DBus bus not connected"):
                get_bus_instance()
        finally:
            dc._bus = original


class TestBroadcastToClientsExtended:
    """Extended broadcast tests."""

    def test_broadcast_with_clients(self):
        """Test broadcast with connected clients."""
        import asyncio
        from unittest.mock import AsyncMock

        # Save original state
        import swb.dbus_client as dc
        from swb.dbus_client import _broadcast_to_clients, _clients_lock, _connected_clients, _loop

        original_clients = dc._connected_clients
        original_lock = dc._clients_lock
        original_loop = dc._loop

        try:
            # Set up test state
            dc._connected_clients = set()
            dc._clients_lock = MagicMock()
            dc._clients_lock.__enter__ = MagicMock(return_value=None)
            dc._clients_lock.__exit__ = MagicMock(return_value=None)
            dc._loop = MagicMock()

            # Add mock client
            mock_ws = AsyncMock()
            mock_ws.send_str = AsyncMock()
            dc._connected_clients.add(mock_ws)

            _broadcast_to_clients({"signal": "test"})

            # Verify loop was called to schedule send
            dc._loop.call_soon_threadsafe.assert_called()
        finally:
            dc._connected_clients = original_clients
            dc._clients_lock = original_lock
            dc._loop = original_loop

    def test_broadcast_with_send_method(self):
        """Test broadcast to client with send method."""
        from unittest.mock import AsyncMock

        # Save original state
        import swb.dbus_client as dc
        from swb.dbus_client import _broadcast_to_clients

        original_clients = dc._connected_clients
        original_lock = dc._clients_lock
        original_loop = dc._loop

        try:
            dc._connected_clients = set()
            dc._clients_lock = MagicMock()
            dc._clients_lock.__enter__ = MagicMock(return_value=None)
            dc._clients_lock.__exit__ = MagicMock(return_value=None)
            dc._loop = MagicMock()

            # Add mock client without send_str (uses send)
            mock_ws = AsyncMock()
            del mock_ws.send_str
            mock_ws.send = AsyncMock()
            dc._connected_clients.add(mock_ws)

            _broadcast_to_clients({"signal": "test"})

            dc._loop.call_soon_threadsafe.assert_called()
        finally:
            dc._connected_clients = original_clients
            dc._clients_lock = original_lock
            dc._loop = original_loop


class TestHandleDbusErrorExtended:
    """Extended DBus error handling tests."""

    def test_connection_error_triggers_reconnect(self):
        """Test connection error triggers reconnect."""
        import threading

        # Save original state
        import swb.dbus_client as dc
        from swb.dbus_client import _dbus_connected, _reconnect_thread, handle_dbus_error

        original_connected = dc._dbus_connected
        original_thread = dc._reconnect_thread

        try:
            dc._dbus_connected = True
            dc._reconnect_thread = None

            # Create mock DBus exception
            mock_exc = MagicMock()
            mock_exc.get_dbus_name.return_value = "org.freedesktop.DBus.Error.ServiceUnknown"

            with patch("swb.dbus_client.dbus.exceptions.DBusException", type(mock_exc)):
                with pytest.raises(Exception):
                    handle_dbus_error(mock_exc)

            # Verify disconnected state
            assert dc._dbus_connected is False
        finally:
            dc._dbus_connected = original_connected
            dc._reconnect_thread = original_thread

    def test_non_connection_error_raised_immediately(self):
        """Test non-connection errors are raised immediately."""
        from swb.dbus_client import handle_dbus_error

        # Create mock DBus exception for non-connection error
        mock_exc = MagicMock()
        mock_exc.get_dbus_name.return_value = "org.freedesktop.DBus.Error.InvalidArgs"

        with patch("swb.dbus_client.dbus.exceptions.DBusException", type(mock_exc)):
            with pytest.raises(Exception):
                handle_dbus_error(mock_exc)


class TestBroadcastExceptions:
    """Test broadcast exception handling."""

    def test_broadcast_exception_during_send(self):
        """Test broadcast handles exception during send."""
        from unittest.mock import AsyncMock

        # Save original state
        import swb.dbus_client as dc
        from swb.dbus_client import _broadcast_to_clients

        original_clients = dc._connected_clients
        original_lock = dc._clients_lock
        original_loop = dc._loop

        try:
            dc._connected_clients = set()
            dc._clients_lock = MagicMock()
            dc._clients_lock.__enter__ = MagicMock(return_value=None)
            dc._clients_lock.__exit__ = MagicMock(return_value=None)
            dc._loop = MagicMock()

            # Add mock client that raises exception during send
            mock_ws = AsyncMock()
            mock_ws.send_str = AsyncMock(side_effect=Exception("Connection closed"))
            dc._connected_clients.add(mock_ws)

            # Should not raise
            _broadcast_to_clients({"signal": "test"})
        finally:
            dc._connected_clients = original_clients
            dc._clients_lock = original_lock
            dc._loop = original_loop
