"""DBus client with auto-reconnection support."""

from __future__ import annotations

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


def _autodiscover_object_path(bus: dbus.Bus) -> str:
    """Discover the per-account object path.

    Multi-account mode: calls SignalControl.listAccounts() to find account sub-paths.
    Single-account mode: the root object already implements org.asamk.Signal directly,
    so listAccounts() will fail - fall back to the root path in that case.
    """
    root = bus.get_object("org.asamk.Signal", "/org/asamk/Signal")
    try:
        control = dbus.Interface(root, "org.asamk.SignalControl")
        accounts = control.listAccounts()  # type: ignore[attr-defined]
    except dbus.exceptions.DBusException:
        # Single-account mode: root object is org.asamk.Signal, not SignalControl
        logging.info("signal-cli running in single-account mode, using root path")
        return "/org/asamk/Signal"
    if not accounts:
        logging.warning("No accounts registered in signal-cli, using root path")
        return "/org/asamk/Signal"
    if len(accounts) > 1:
        logging.warning(f"Multiple accounts found: {list(accounts)}. Set SIGNAL_ACCOUNT to select one explicitly.")
    path = str(accounts[0])
    logging.info(f"Auto-discovered account path: {path}")
    return path


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
            # Remove signal receiver from the old bus before replacing it.
            # Without this, GLib retains a C-level reference to the old bus
            # keeping its receiver alive alongside the new one, causing every
            # incoming signal to be delivered N+1 times after N reconnects.
            if _bus is not None and signal_handler is not None:
                try:
                    _bus.remove_signal_receiver(signal_handler, dbus_interface="org.asamk.Signal")
                except Exception:  # nosec B110 - Intentionally ignore cleanup failures
                    pass

            _bus = get_bus(config)
            if _bus is None:
                return False

            root_obj = _bus.get_object("org.asamk.Signal", "/org/asamk/Signal", introspect=False)

            # Detect mode via listAccounts() - it only exists on SignalControl
            # (multi-account mode). signal-cli responds to version() regardless of
            # which interface is specified, so version() alone cannot detect the mode.
            try:
                control = dbus.Interface(root_obj, "org.asamk.SignalControl")
                exported_accounts = [str(p) for p in control.listAccounts()]  # type: ignore
                single_account_mode = False
            except dbus.exceptions.DBusException as exc:
                if "UnknownMethod" not in exc.get_dbus_name():
                    raise  # Transport/service error, not a mode issue
                # Single-account mode: root IS the account, implements org.asamk.Signal
                dbus.Interface(root_obj, "org.asamk.Signal").version()  # type: ignore  liveness probe
                single_account_mode = True
                exported_accounts = []
                logging.info("signal-cli running in single-account mode")

            if single_account_mode:
                object_path = "/org/asamk/Signal"
            else:
                object_path = _build_object_path(config)
                if object_path == "/org/asamk/Signal":
                    object_path = _autodiscover_object_path(_bus)
                # Verify the per-account path is already exported. signal-cli
                # registers the service name before account objects are ready.
                if object_path != "/org/asamk/Signal" and object_path not in exported_accounts:
                    raise dbus.exceptions.DBusException(f"Account path {object_path} not yet exported by signal-cli (exported: {exported_accounts})")

            _signal_object = _bus.get_object("org.asamk.Signal", object_path, introspect=False)
            _signal_interface = dbus.Interface(_signal_object, "org.asamk.Signal")

            _dbus_connected = True
            _reconnect_backoff = 1
            logging.info(f"Connected to signal-cli at {object_path}")

            if signal_handler is not None:
                _bus.add_signal_receiver(
                    signal_handler,
                    dbus_interface="org.asamk.Signal",
                    member_keyword="member",
                    path_keyword="path",
                )

            # Clear stale introspection cache so /asyncapi reflects the live instance
            from swb.asyncapi import clear_introspection_cache

            clear_introspection_cache()

            if _initial_connect:
                _initial_connect = False
            else:
                _broadcast_to_clients({"signal": "Reconnected"})
                # Re-subscribe for keep-alive if clients were connected during the outage
                if _connected_clients and _signal_interface is not None:
                    try:
                        _signal_interface.subscribeReceive()  # type: ignore[attr-defined]
                    except Exception as exc:
                        logging.warning(f"subscribeReceive after reconnect failed: {exc}")

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


def subscribe_receive() -> None:
    """Register a keep-alive token for the unidentified Signal WebSocket.

    Calls subscribeReceive() on signal-cli, which increments an internal counter and
    registers keep-alive tokens on both Signal WebSockets when the counter goes 0→1.
    Call once per connected bridge client (or at least on first-client transition).
    """
    try:
        get_interface().subscribeReceive()  # type: ignore[attr-defined]
        logging.debug("subscribeReceive() called - keep-alive active")
    except Exception as exc:
        logging.warning(f"subscribeReceive failed: {exc}")


def unsubscribe_receive() -> None:
    """Remove a keep-alive token, stopping keep-alive when the counter reaches zero.

    Calls unsubscribeReceive() on signal-cli, which decrements the internal counter
    and removes keep-alive tokens when the counter reaches zero.
    Call once per disconnecting bridge client (or at least on last-client transition).
    """
    try:
        get_interface().unsubscribeReceive()  # type: ignore[attr-defined]
        logging.debug("unsubscribeReceive() called")
    except Exception as exc:
        logging.warning(f"unsubscribeReceive failed: {exc}")


def is_connected() -> bool:
    """Check if DBus connection is active."""
    return _dbus_connected


def get_interface() -> dbus.Interface:
    """Get the signal-cli DBus interface."""
    if _signal_interface is None:
        raise RuntimeError("DBus interface not connected")
    return _signal_interface


def get_interface_for_account(account: str | None) -> dbus.Interface:
    """Get DBus interface for a specific account number, or the default if None."""
    if account is None:
        return get_interface()
    bus = get_bus_instance()
    dbus_number = account.replace("+", "_")
    path = f"/org/asamk/Signal/{dbus_number}"
    obj = bus.get_object("org.asamk.Signal", path)
    return dbus.Interface(obj, "org.asamk.Signal")


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
