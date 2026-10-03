"""Asyncio-native DBus client for signal-cli (dbus-fast), with auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from swb.config import Config

_SIGNAL_BUS_NAME = "org.asamk.Signal"
_SIGNAL_ROOT_PATH = "/org/asamk/Signal"
_SIGNAL_IFACE = "org.asamk.Signal"
_CONTROL_IFACE = "org.asamk.SignalControl"
_DAEMON_NAME = "org.freedesktop.DBus"
_DAEMON_PATH = "/org/freedesktop/DBus"

# Error names that mean the connection to signal-cli is gone
_CONNECTION_ERROR_NAMES = ("ServiceUnknown", "NoReply", "Disconnected", "UnknownObject")

# Transport-level failures raised by in-flight calls on a dead bus
_TRANSPORT_ERRORS = (OSError, EOFError, BrokenPipeError, TimeoutError)

_MAX_BACKOFF = 60  # seconds


def _log_send_error(future) -> None:
    """Done-callback for broadcast send tasks - logs failures at DEBUG level."""
    try:
        future.result()
    except Exception as exc:
        logging.debug(f"Failed to broadcast to client: {exc}")


class BoundInterface:
    """Calls a named DBus interface on a fixed object path.

    Deliberately avoids introspection-derived proxies: signal-cli's root
    object dispatches org.asamk.Signal methods even when the interface is not
    declared in introspection data (e.g. while no account is registered),
    which introspection-bound proxies cannot express.
    """

    def __init__(self, bus: MessageBus, path: str, iface_name: str):
        self._bus = bus
        self._path = path
        self._iface = iface_name

    async def call(self, member: str, signature: str, body: list) -> Any:
        """Invoke member on the interface; unwrap reply body like dbus-python did."""
        reply = await self._bus.call(
            Message(
                destination=_SIGNAL_BUS_NAME,
                path=self._path,
                interface=self._iface,
                member=member,
                signature=signature,
                body=body,
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise DBusError._from_message(reply)
        if not reply.body:
            return None
        if len(reply.body) == 1:
            return reply.body[0]
        return reply.body


class SignalClient:
    """Asyncio-native signal-cli DBus client.

    Owns the bus connection, per-account interfaces, signal dispatch,
    and reconnect state. Everything runs on the event loop - no threads.
    """

    def __init__(self, config: Config, signal_handler: Callable, connected_clients: set):
        self.config = config
        self._signal_handler = signal_handler
        self._connected_clients = connected_clients

        self.bus: MessageBus | None = None
        self._signal_iface: BoundInterface | None = None
        self._object_path = _SIGNAL_ROOT_PATH
        self._introspection = None  # intr.Node of the connected account object
        self._account_ifaces: dict[str, BoundInterface] = {}

        self.connected = False
        self.single_account_mode = False

        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_wake = asyncio.Event()
        self._watch_task: asyncio.Task | None = None
        self._initial_connect = True

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _object_path_for(self, config: Config) -> str:
        """Build DBus object path from account number."""
        if config.account:
            return f"{_SIGNAL_ROOT_PATH}/{config.account.replace('+', '_')}"
        return _SIGNAL_ROOT_PATH

    async def connect(self) -> bool:
        """Connect to the signal-cli DBus interface. Returns True on success."""
        old_bus = self.bus
        try:
            bus = MessageBus(bus_type=BusType.SESSION if self.config.bus == "session" else BusType.SYSTEM)
            await bus.connect()

            control = BoundInterface(bus, _SIGNAL_ROOT_PATH, _CONTROL_IFACE)
            signal_root = BoundInterface(bus, _SIGNAL_ROOT_PATH, _SIGNAL_IFACE)

            # Detect mode via introspection: SignalControl only exists in
            # multi-account mode. In single-account mode the root object
            # implements org.asamk.Signal directly.
            root_node = await bus.introspect(_SIGNAL_BUS_NAME, _SIGNAL_ROOT_PATH)
            iface_names = {i.name for i in root_node.interfaces}

            if _CONTROL_IFACE in iface_names:
                single = False
                exported_accounts = [str(p) for p in await control.call("listAccounts", "", []) or []]
            else:
                await signal_root.call("version", "", [])  # liveness probe
                single = True
                exported_accounts = []
                logging.info("signal-cli running in single-account mode")

            if single:
                object_path = _SIGNAL_ROOT_PATH
            else:
                object_path = self._object_path_for(self.config)
                if object_path == _SIGNAL_ROOT_PATH:
                    object_path = self._autodiscover_object_path(exported_accounts)
                if object_path != _SIGNAL_ROOT_PATH and object_path not in exported_accounts:
                    raise DBusError(
                        "org.asamk.Signal.Error.AccountNotExported",
                        f"Account path {object_path} not yet exported by signal-cli (exported: {exported_accounts})",
                    )

            # Introspection of the selected object for AsyncAPI generation
            node = await bus.introspect(_SIGNAL_BUS_NAME, object_path)

            # Route signals to our message handler: all org.asamk.Signal
            # emissions, plus NameOwnerChanged for fast outage detection.
            await self._add_match_on(bus, "type='signal',interface='org.asamk.Signal'")
            await self._add_match_on(
                bus,
                "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged'",
            )
            bus.add_message_handler(self._handle_message)

            self.bus = bus
            self._signal_iface = BoundInterface(bus, object_path, _SIGNAL_IFACE)
            self._object_path = object_path
            self._introspection = node
            self._account_ifaces.clear()
            self.single_account_mode = single
            self.connected = True

            if old_bus is not None:
                old_bus.disconnect()

            self._watch_task = asyncio.create_task(self._watch_transport(bus))
            logging.info(f"Connected to signal-cli at {object_path}")

            if self._initial_connect:
                self._initial_connect = False
            else:
                self._broadcast({"signal": "Reconnected"})
                # Re-subscribe for keep-alive if clients were connected during the outage
                if self._connected_clients:
                    try:
                        await self._signal_iface.call("subscribeReceive", "", [])
                    except Exception as exc:
                        logging.warning(f"subscribeReceive after reconnect failed: {exc}")

            return True

        except Exception as exc:
            logging.error(f"DBus connection failed: {exc}")
            self.connected = False
            return False

    async def _add_match_on(self, bus: MessageBus, rule: str) -> None:
        """Register a signal match rule with the bus daemon."""
        reply = await bus.call(
            Message(
                destination=_DAEMON_NAME,
                path=_DAEMON_PATH,
                interface=_DAEMON_NAME,
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise DBusError(reply.error_name or "org.freedesktop.DBus.Error.Failed", str(reply.body))

    def _autodiscover_object_path(self, accounts: list[str]) -> str:
        """Pick the account sub-path when signal-cli runs multi-account."""
        if not accounts:
            logging.warning("No accounts registered in signal-cli, using root path")
            return _SIGNAL_ROOT_PATH
        if len(accounts) > 1:
            logging.warning(f"Multiple accounts found: {list(accounts)}. Set SIGNAL_ACCOUNT to select one explicitly.")
        path = str(accounts[0])
        logging.info(f"Auto-discovered account path: {path}")
        return path

    # ------------------------------------------------------------------
    # Disconnect / reconnect
    # ------------------------------------------------------------------

    def _handle_message(self, msg: Message):
        """dbus-fast message handler - runs on the event loop."""
        if msg.message_type is not MessageType.SIGNAL:
            return None
        if msg.interface == _SIGNAL_IFACE:
            self._signal_handler(msg)
        elif msg.member == "NameOwnerChanged" and msg.interface == _DAEMON_NAME:
            self._on_name_owner_changed(msg.body)
        return None

    def _on_name_owner_changed(self, body) -> None:
        """Track org.asamk.Signal ownership: vanish -> instant outage detection;
        reappear -> wake the reconnect loop for an immediate retry."""
        name, _old_owner, new_owner = body[0], body[1], body[2]
        if name != _SIGNAL_BUS_NAME:
            return
        if not new_owner:
            self._on_connection_lost(f"{_SIGNAL_BUS_NAME} vanished from the bus")
        elif not self.connected:
            self._reconnect_wake.set()

    async def _watch_transport(self, bus: MessageBus) -> None:
        """Resolve when the transport dies (e.g. dbus-daemon itself exits)."""
        await bus.wait_for_disconnect()
        if bus is self.bus:
            self._on_connection_lost("bus connection closed")

    def _on_connection_lost(self, reason: str) -> None:
        """Mark the connection down, notify clients, and start the reconnect task."""
        if self.connected:
            logging.warning(f"DBus connection lost: {reason}")
            self.connected = False
            self._broadcast({"signal": "Disconnected"})

        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Retry connecting with exponential backoff until connected."""
        backoff = 1
        while not self.connected:
            logging.info(f"Reconnecting in {backoff}s...")
            try:
                await asyncio.wait_for(self._reconnect_wake.wait(), timeout=backoff)
            except TimeoutError:
                pass
            self._reconnect_wake.clear()
            if await self.connect():
                logging.info("Reconnected to signal-cli")
                return
            backoff = min(backoff * 2, _MAX_BACKOFF)

    def note_error(self, exc: Exception) -> None:
        """Classify a failed call: connection errors trigger the reconnect path."""
        if isinstance(exc, DBusError):
            if not any(e in (exc.type or "") for e in _CONNECTION_ERROR_NAMES):
                return  # application-level error - caller reports it, no reconnect
        elif not isinstance(exc, _TRANSPORT_ERRORS):
            return  # not a connection failure either

        self._on_connection_lost(getattr(exc, "type", None) or str(exc))

    # ------------------------------------------------------------------
    # Interfaces and calls
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        return self.connected

    @property
    def introspection(self):
        """Introspection Node of the connected account object (for AsyncAPI)."""
        return self._introspection

    def interface(self, account: str | None) -> BoundInterface:
        """Return the org.asamk.Signal interface for an account (or default)."""
        if self._signal_iface is None:
            raise RuntimeError("DBus interface not connected")
        if account is None:
            return self._signal_iface
        if account not in self._account_ifaces:
            if self.bus is None:
                raise RuntimeError("DBus bus not connected")
            path = f"{_SIGNAL_ROOT_PATH}/{account.replace('+', '_')}"
            self._account_ifaces[account] = BoundInterface(self.bus, path, _SIGNAL_IFACE)
        return self._account_ifaces[account]

    def sub_interface(self, path: str, iface_name: str) -> BoundInterface:
        """Return a bound interface for a sub-object (groups, identities)."""
        if self.bus is None:
            raise RuntimeError("DBus bus not connected")
        return BoundInterface(self.bus, path, iface_name)

    async def subscribe_receive(self) -> None:
        """Register a keep-alive token for the unidentified Signal WebSocket."""
        try:
            if self._signal_iface is not None:
                await self._signal_iface.call("subscribeReceive", "", [])
            logging.debug("subscribeReceive() called - keep-alive active")
        except Exception as exc:
            logging.warning(f"subscribeReceive failed: {exc}")

    async def unsubscribe_receive(self) -> None:
        """Remove a keep-alive token when the last client disconnects."""
        try:
            if self._signal_iface is not None:
                await self._signal_iface.call("unsubscribeReceive", "", [])
            logging.debug("unsubscribeReceive() called")
        except Exception as exc:
            logging.warning(f"unsubscribeReceive failed: {exc}")

    # ------------------------------------------------------------------
    # Broadcast to WebSocket clients
    # ------------------------------------------------------------------

    def _broadcast(self, payload: dict) -> None:
        """Broadcast a system message to all connected WebSocket clients."""
        if not self._connected_clients:
            return
        msg = json.dumps(payload)
        for ws in list(self._connected_clients):
            try:
                coro = ws.send_str(msg) if hasattr(ws, "send_str") else ws.send(msg)
                task = asyncio.create_task(coro)
                task.add_done_callback(_log_send_error)
            except Exception:
                logging.debug("Failed to broadcast to client (disconnected?)", exc_info=True)
