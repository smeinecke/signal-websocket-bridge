"""Entry point for signalbot."""

import asyncio
import logging
import threading
import time

import dbus.exceptions
from gi.repository import GLib

from swb.asyncapi import generate_asyncapi_spec
from swb.config import load_config
from swb.dbus_client import (
    connect_signal_interface,
    get_bus_instance,
    get_interface,
    get_object_instance,
    handle_dbus_error,
    is_connected,
    setup_glib_loop,
)
from swb.dispatch import MethodDispatcher
from swb.signals import create_signal_handler
from swb.websocket_server import WebSocketServer

_WATCHDOG_INTERVAL = 30  # seconds between liveness probes


def _run_watchdog(get_iface, stop_event: threading.Event) -> None:
    """Periodically probe signal-cli via DBus; trigger reconnect on failure."""
    while not stop_event.wait(_WATCHDOG_INTERVAL):
        if not is_connected():
            continue
        try:
            get_iface().version()  # type: ignore[attr-defined]
        except dbus.exceptions.DBusException as exc:
            logging.warning(f"Watchdog detected DBus failure: {exc}")
            handle_dbus_error(exc)


def main():
    """Main entry point."""
    config = load_config()
    setup_glib_loop()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    glib_loop = GLib.MainLoop()
    glib_thread = threading.Thread(target=glib_loop.run, daemon=True)
    glib_thread.start()

    # Create client tracking state upfront so the DBus signal handler
    # and WebSocketServer share the same objects from the start.
    connected_clients: set = set()
    clients_lock = threading.Lock()

    signal_handler = create_signal_handler(connected_clients, clients_lock, loop)

    backoff = 1
    while not connect_signal_interface(config, loop, signal_handler, connected_clients, clients_lock):
        logging.info(f"Waiting for signal-cli on {config.bus} bus, retrying in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)

    dispatcher = MethodDispatcher(get_interface, get_bus_instance)

    def dispatch_with_reconnect(method: str, params: dict):
        try:
            return dispatcher.dispatch(method, params)
        except dbus.exceptions.DBusException as exc:
            # Triggers background reconnect thread, then re-raises so the
            # client receives an error. Client should retry after "Reconnected".
            handle_dbus_error(exc)

    def get_asyncapi_spec() -> dict:
        return generate_asyncapi_spec(config, get_object_instance())

    stop_watchdog = threading.Event()
    watchdog_thread = threading.Thread(target=_run_watchdog, args=(get_interface, stop_watchdog), daemon=True)
    watchdog_thread.start()

    server = WebSocketServer(
        config=config,
        dispatch_func=dispatch_with_reconnect,
        asyncapi_json_func=get_asyncapi_spec,
        asyncapi_yaml_func=get_asyncapi_spec,
        connected_clients=connected_clients,
        clients_lock=clients_lock,
    )

    try:
        loop.run_until_complete(server.run())
    except KeyboardInterrupt:
        pass
    finally:
        stop_watchdog.set()
        glib_loop.quit()


if __name__ == "__main__":
    main()
