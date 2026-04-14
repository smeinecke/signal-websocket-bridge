"""DBus signal handling and serialization."""

import asyncio
import json
import logging
from typing import Any

from swb.types import dbus_to_native


def _log_send_error(future) -> None:
    """Done-callback for run_coroutine_threadsafe — logs failed sends at DEBUG level."""
    try:
        future.result()
    except Exception as exc:
        logging.debug(f"Failed to send signal to client: {exc}")


def serialize_signal(signal_name: str, args: tuple) -> dict:
    """Convert positional DBus signal args to named fields.

    Known signals get structured payloads; unknown signals fall back to {signal, args}.
    """
    native_args = [dbus_to_native(a) for a in args]

    if signal_name == "MessageReceived" and len(native_args) >= 5:
        return {
            "signal": signal_name,
            "timestamp": native_args[0],
            "sender": native_args[1],
            "groupId": native_args[2] if native_args[2] else None,  # empty -> None
            "message": native_args[3],
            "attachments": native_args[4] if len(native_args) > 4 else [],
        }

    if signal_name == "SyncMessageReceived" and len(native_args) >= 6:
        return {
            "signal": signal_name,
            "timestamp": native_args[0],
            "sender": native_args[1],
            "destination": native_args[2],
            "groupId": native_args[3] if native_args[3] else None,
            "message": native_args[4],
            "attachments": native_args[5] if len(native_args) > 5 else [],
        }

    if signal_name == "ReceiptReceived" and len(native_args) >= 2:
        return {
            "signal": signal_name,
            "timestamp": native_args[0],
            "sender": native_args[1],
        }

    # Unknown signal - generic format
    return {"signal": signal_name, "args": native_args}


def create_signal_handler(connected_clients: set, clients_lock: Any, loop: Any):
    """Create a DBus signal handler that broadcasts to WebSocket clients."""

    def handler(*args, **kwargs):
        """Called from the GLib thread on every org.asamk.Signal emission."""
        signal_name = kwargs.get("member", "unknown")
        payload_dict = serialize_signal(signal_name, args)
        payload = json.dumps(payload_dict)
        logging.debug(f"DBus signal [{signal_name}]: {payload}")

        with clients_lock:
            clients_snapshot = list(connected_clients)

        for ws in clients_snapshot:
            coro = ws.send_str(payload) if hasattr(ws, "send_str") else ws.send(payload)
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            future.add_done_callback(_log_send_error)

    return handler
