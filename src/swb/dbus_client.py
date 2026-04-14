"""DBus client with auto-reconnection support."""

import json
import logging
import threading
import time
from typing import Any, Callable

import dbus
import dbus.mainloop.glib

from swb.config import Config

# Global state
_bus: dbus.Bus | None = None
_signal_object: dbus.ProxyObject | None = None
_signal_interface: dbus.Interface | None = None
_reconnect_lock = threading.Lock()
_reconnect_backoff = 1  # seconds, doubles up to 60s cap
_dbus_connected = False
_reconnect_thread: threading.Thread | None = None
_initial_connect = True  # distinguishes first connect from reconnect

# Stored at connect time so the reconnect thread can use them
_config: Config | None = None
_loop: Any = None
_signal_handler: Callable | None = None
_connected_clients: set = set()
_clients_lock: threading.Lock | None = None


def setup_glib_loop():
    """Initialize GLib main loop for DBus."""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


def _build_object_path(config: Config) -> str:
    """Build DBus object path from account number."""
    if config.account:
        # +4915... -> /org/asamk/Signal/_4915...
        dbus_number = config.account.replace("+", "_")
        return f"/org/asamk/Signal/{dbus_number}"
    return "/org/asamk/Signal"


def get_bus(config: Config) -> dbus.Bus:
    """Get the appropriate DBus bus."""
    if config.bus == "session":
        logging.info("Using DBus SessionBus")
        return dbus.SessionBus()
    else:
        logging.info("Using DBus SystemBus")
        return dbus.SystemBus()


def connect_signal_interface(
    config: Config,
    loop: Any,
    signal_handler: Callable,
    connected_clients: set,
    clients_lock: threading.Lock,
) -> bool:
    """Connect to signal-cli DBus interface. Returns True on success."""
    global _bus, _signal_object, _signal_interface, _dbus_connected, _reconnect_backoff
    global _loop, _signal_handler, _connected_clients, _clients_lock, _config, _initial_connect

    _config = config
    _loop = loop
    _signal_handler = signal_handler
    _connected_clients = connected_clients
    _clients_lock = clients_lock

    with _reconnect_lock:
        try:
            _bus = get_bus(config)
            if _bus is None:
                return False

            object_path = _build_object_path(config)
            _signal_object = _bus.get_object("org.asamk.Signal", object_path)
            _signal_interface = dbus.Interface(_signal_object, "org.asamk.Signal")
            # Verify connection works
            _signal_interface.version()  # type: ignore

            _dbus_connected = True
            _reconnect_backoff = 1
            logging.info(f"Connected to signal-cli at {object_path}")

            if signal_handler is not None:
                _bus.add_signal_receiver(
                    signal_handler,
                    dbus_interface="org.asamk.Signal",
                    member_keyword="member",
                )

            # Clear stale introspection cache so /asyncapi reflects the live instance
            from swb.asyncapi import clear_introspection_cache
            clear_introspection_cache()

            if _initial_connect:
                _initial_connect = False
            else:
                _broadcast_to_clients({"signal": "Reconnected"})

            return True

        except Exception as exc:
            logging.error(f"DBus connection failed: {exc}")
            _dbus_connected = False
            return False


def _reconnect_loop():
    """Background thread: retry connecting with exponential backoff."""
    global _reconnect_backoff

    while not _dbus_connected:
        logging.info(f"Reconnecting in {_reconnect_backoff}s...")
        time.sleep(_reconnect_backoff)
        _reconnect_backoff = min(_reconnect_backoff * 2, 60)

        if _config is None:
            continue

        if _signal_handler is None or _clients_lock is None:
            continue
        if connect_signal_interface(_config, _loop, _signal_handler, _connected_clients, _clients_lock):
            logging.info("Reconnected to signal-cli")
            break


def _broadcast_to_clients(payload: dict) -> None:
    """Broadcast a system message to all connected WebSocket clients."""
    if not _connected_clients or not _clients_lock:
        return

    msg = json.dumps(payload)
    with _clients_lock:
        clients_snapshot = list(_connected_clients)

    import asyncio

    for ws in clients_snapshot:
        try:
            if hasattr(ws, "send_str"):
                asyncio.run_coroutine_threadsafe(ws.send_str(msg), _loop)
            else:
                asyncio.run_coroutine_threadsafe(ws.send(msg), _loop)
        except Exception:
            logging.debug("Failed to broadcast to client (disconnected?)", exc_info=True)


def handle_dbus_error(exc: Exception) -> None:
    """On DBus connection errors: mark disconnected, start background reconnect, re-raise.

    Non-connection DBus errors are re-raised immediately without triggering reconnect.
    """
    global _dbus_connected, _reconnect_thread

    if not isinstance(exc, dbus.exceptions.DBusException):
        raise exc

    error_name = exc.get_dbus_name()  # type: ignore[union-attr]
    is_connection_error = any(e in error_name for e in ("ServiceUnknown", "NoReply", "Disconnected", "UnknownObject"))

    if not is_connection_error:
        raise exc

    if _dbus_connected:
        logging.warning(f"DBus connection lost: {error_name}")
        _dbus_connected = False
        _broadcast_to_clients({"signal": "Disconnected"})

    # Start background reconnect thread if not already running
    if _reconnect_thread is None or not _reconnect_thread.is_alive():
        _reconnect_thread = threading.Thread(target=_reconnect_loop, daemon=True)
        _reconnect_thread.start()

    raise exc


def is_connected() -> bool:
    """Check if DBus connection is active."""
    return _dbus_connected


def get_interface() -> dbus.Interface:
    """Get the signal-cli DBus interface."""
    if _signal_interface is None:
        raise RuntimeError("DBus interface not connected")
    return _signal_interface


def get_object_instance():  # -> dbus.ProxyObject
    """Get the signal-cli DBus proxy object (needed for introspection)."""
    if _signal_object is None:
        raise RuntimeError("DBus object not connected")
    return _signal_object


def get_bus_instance() -> dbus.Bus:
    """Get the DBus bus instance."""
    if _bus is None:
        raise RuntimeError("DBus bus not connected")
    return _bus
