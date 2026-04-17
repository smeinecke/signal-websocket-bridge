"""DBus signal handling and serialization."""

import asyncio
import json
import logging
import uuid
from typing import Any

from swb.types import dbus_to_native

_SIGNAL_ROOT = "/org/asamk/Signal"
_SIGNAL_PREFIX = "/org/asamk/Signal/"


def _path_to_account(path: str) -> str | None:
    """Derive the E.164 account number from a DBus object path.

    /org/asamk/Signal/_491234567890  →  +491234567890
    /org/asamk/Signal                →  None  (single-account mode)
    """
    if not path.startswith(_SIGNAL_PREFIX):
        return None
    suffix = path[len(_SIGNAL_PREFIX):]
    if suffix.startswith("_"):
        return "+" + suffix[1:]
    return suffix or None


def _log_send_error(future) -> None:
    """Done-callback for run_coroutine_threadsafe - logs failed sends at DEBUG level."""
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


def create_signal_handler(connected_clients: set, clients_lock: Any, loop: Any, event_buffer=None):
    """Create a DBus signal handler that broadcasts to WebSocket clients.

    If event_buffer (a collections.deque) is provided, each serialized event is
    appended to it before broadcasting so new clients can replay missed events.
    """

    def handler(*args, **kwargs):
        """Called from the GLib thread on every org.asamk.Signal emission."""
        signal_name = kwargs.get("member", "unknown")
        payload_dict = serialize_signal(signal_name, args)

        account = _path_to_account(kwargs.get("path", ""))
        if account:
            payload_dict["account"] = account

        payload_dict["event_id"] = str(uuid.uuid4())
        payload = json.dumps(payload_dict)
        logging.debug(f"DBus signal [{signal_name}] account={account}: {payload}")

        if event_buffer is not None:
            event_buffer.append(payload)  # deque.append is thread-safe in CPython

        with clients_lock:
            clients_snapshot = list(connected_clients)

        for ws in clients_snapshot:
            coro = ws.send_str(payload) if hasattr(ws, "send_str") else ws.send(payload)
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            future.add_done_callback(_log_send_error)

    return handler
