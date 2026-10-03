"""Entry point for signalbot."""

import asyncio
import logging
from collections import deque

from swb.asyncapi import generate_asyncapi_spec
from swb.config import load_config
from swb.dbus_client import SignalClient
from swb.dispatch import MethodDispatcher
from swb.signals import create_signal_handler
from swb.websocket_server import WebSocketServer


async def _run(config) -> None:
    """Async entry: connect to signal-cli, then serve until cancelled."""
    connected_clients: set = set()

    event_buffer = deque(maxlen=config.buffer_size) if config.buffer_size > 0 else None
    if event_buffer is not None:
        logging.info(f"Event buffer enabled: up to {config.buffer_size} events will be replayed on client reconnect")

    signal_handler = create_signal_handler(connected_clients, event_buffer)
    client = SignalClient(config, signal_handler, connected_clients)

    backoff = 1
    while not await client.connect():
        logging.info(f"Waiting for signal-cli on {config.bus} bus, retrying in {backoff}s...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)

    def make_dispatch(account: str | None):
        """Create a per-connection dispatch coroutine for the given account (or default)."""
        return MethodDispatcher(client, account).dispatch

    def get_asyncapi_spec() -> dict:
        return generate_asyncapi_spec(config, client.introspection)

    server = WebSocketServer(
        config=config,
        dispatch_factory=make_dispatch,
        asyncapi_json_func=get_asyncapi_spec,
        asyncapi_yaml_func=get_asyncapi_spec,
        is_connected=client.is_connected,
        subscribe=client.subscribe_receive,
        unsubscribe=client.unsubscribe_receive,
        connected_clients=connected_clients,
        event_buffer=event_buffer,
    )

    await server.run()


def main():
    """Main entry point."""
    config = load_config()
    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
