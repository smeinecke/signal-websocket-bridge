"""Tests for swb.dbus_client.SignalClient (dbus-fast based)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dbus_fast import Message, MessageType
from dbus_fast import introspection as intr
from dbus_fast.errors import DBusError

from swb.config import Config
from swb.dbus_client import SignalClient

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

_ROOT_SINGLE_XML = """<node>
  <interface name="org.asamk.Signal">
    <method name="version"><arg direction="out" type="s"/></method>
    <signal name="MessageReceived"><arg type="x"/><arg type="s"/><arg type="ay"/><arg type="s"/><arg type="as"/></signal>
  </interface>
</node>"""

_ROOT_MULTI_XML = """<node>
  <interface name="org.asamk.SignalControl">
    <method name="listAccounts"><arg direction="out" type="ao"/></method>
    <method name="version"><arg direction="out" type="s"/></method>
  </interface>
</node>"""


def make_node(xml: str):
    return intr.Node.parse(xml)


@pytest.fixture
def config():
    return Config(bus="session", host="localhost", port=9999, token=None, account=None, log_level="INFO", buffer_size=0)


@pytest.fixture
def clients():
    return set()


@pytest.fixture
def signal_handler():
    return MagicMock()


@pytest.fixture
def client(config, signal_handler, clients):
    return SignalClient(config, signal_handler, clients)


def make_bus(nodes: dict[str, intr.Node], method_replies: dict[tuple[str, str], list] | None = None):
    """Fake MessageBus.

    introspect(name, path) -> nodes[path]
    call(msg) -> dispatches on msg.member via method_replies {(path, member): body}
    """
    bus = MagicMock()
    bus.connect = AsyncMock()
    method_replies = method_replies or {}

    async def introspect(name, path):
        return nodes[path]

    bus.introspect = AsyncMock(side_effect=introspect)

    bus.calls = []  # (member, path, interface, signature, body) log

    async def call(msg: Message):
        msg.serial = 1
        bus.calls.append((msg.member, msg.path, msg.interface, msg.signature, msg.body))
        if msg.member == "AddMatch":
            return Message.new_method_return(msg, signature="", body=[])
        body = method_replies.get((msg.path, msg.member), [])
        if isinstance(body, Exception):
            raise body
        return Message.new_method_return(msg, signature="", body=body)

    bus.call = AsyncMock(side_effect=call)
    bus.add_message_handler = MagicMock()
    bus.disconnect = MagicMock()

    disconnected = asyncio.Event()
    bus.wait_for_disconnect = AsyncMock(side_effect=disconnected.wait)
    bus._disconnect_event = disconnected

    return bus


async def connected_client(client, method_replies=None, multi=False):
    """Connect a client with the standard single/multi-account fake bus."""
    replies = method_replies or {}
    if multi:
        nodes = {"/org/asamk/Signal": make_node(_ROOT_MULTI_XML)}
    else:
        nodes = {"/org/asamk/Signal": make_node(_ROOT_SINGLE_XML)}
        replies.setdefault(("/org/asamk/Signal", "version"), ["1.0"])
    bus = make_bus(nodes, replies)
    with patch("swb.dbus_client.MessageBus", return_value=bus):
        await client.connect()
    return bus


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------


class TestConnect:
    async def test_connect_single_account(self, client):
        """Single-account mode when SignalControl interface is absent."""
        bus = await connected_client(client)

        assert client.connected is True
        assert client.single_account_mode is True
        assert any(c[0] == "version" for c in bus.calls)  # liveness probe
        assert bus.add_message_handler.called

    async def test_connect_multi_account_autodiscover(self, client):
        """Multi-account mode auto-discovers the exported account path."""
        account_path = "/org/asamk/Signal/_491234567890"
        nodes = {"/org/asamk/Signal": make_node(_ROOT_MULTI_XML), account_path: make_node(_ROOT_SINGLE_XML)}
        bus = make_bus(nodes, {("/org/asamk/Signal", "listAccounts"): [[account_path]]})

        with patch("swb.dbus_client.MessageBus", return_value=bus):
            assert await client.connect() is True

        assert client.single_account_mode is False
        assert client._object_path == account_path

    async def test_connect_explicit_account(self, clients):
        """Explicit SIGNAL_ACCOUNT selects that account path."""
        config = Config(bus="session", host="localhost", port=9999, token=None, account="+491234567890", log_level="INFO", buffer_size=0)
        client = SignalClient(config, MagicMock(), clients)

        account_path = "/org/asamk/Signal/_491234567890"
        nodes = {"/org/asamk/Signal": make_node(_ROOT_MULTI_XML), account_path: make_node(_ROOT_SINGLE_XML)}
        bus = make_bus(nodes, {("/org/asamk/Signal", "listAccounts"): [[account_path]]})

        with patch("swb.dbus_client.MessageBus", return_value=bus):
            assert await client.connect() is True
        assert client._object_path == account_path

    async def test_connect_unexported_account_fails(self, clients):
        """Explicit account not in listAccounts -> connect fails."""
        config = Config(bus="session", host="localhost", port=9999, token=None, account="+491111111111", log_level="INFO", buffer_size=0)
        client = SignalClient(config, MagicMock(), clients)

        account_path = "/org/asamk/Signal/_491234567890"
        nodes = {"/org/asamk/Signal": make_node(_ROOT_MULTI_XML)}
        bus = make_bus(nodes, {("/org/asamk/Signal", "listAccounts"): [[account_path]]})

        with patch("swb.dbus_client.MessageBus", return_value=bus):
            assert await client.connect() is False

    async def test_connect_fails_gracefully(self, client):
        """Bus connection failure returns False, no exception."""
        bus = MagicMock()
        bus.connect = AsyncMock(side_effect=OSError("no bus"))

        with patch("swb.dbus_client.MessageBus", return_value=bus):
            result = await client.connect()

        assert result is False
        assert client.connected is False

    async def test_connect_registers_add_match(self, client):
        """Signal routing match rules are registered with the daemon."""
        bus = await connected_client(client)

        rules = [c[4][0] for c in bus.calls if c[0] == "AddMatch"]
        assert any("interface='org.asamk.Signal'" in r for r in rules)
        assert any("NameOwnerChanged" in r for r in rules)


# ---------------------------------------------------------------------------
# Message handling / outage detection
# ---------------------------------------------------------------------------


class TestMessageHandling:
    async def test_signal_dispatched_to_handler(self, client):
        await connected_client(client)

        msg = SimpleNamespace(
            message_type=MessageType.SIGNAL,
            interface="org.asamk.Signal",
            member="MessageReceived",
            body=[1, "+1", b"", "hi", []],
            path="/org/asamk/Signal",
        )
        client._handle_message(msg)

        client._signal_handler.assert_called_once_with(msg)

    async def test_non_signal_ignored(self, client):
        await connected_client(client)

        msg = SimpleNamespace(message_type=MessageType.METHOD_RETURN, interface="x", member="y", body=[], path="/")
        assert client._handle_message(msg) is None
        client._signal_handler.assert_not_called()

    async def test_name_owner_changed_vanish_disconnects(self, client, clients):
        ws = AsyncMock()
        clients.add(ws)
        await connected_client(client)

        msg = SimpleNamespace(
            message_type=MessageType.SIGNAL,
            interface="org.freedesktop.DBus",
            member="NameOwnerChanged",
            body=["org.asamk.Signal", ":1.23", ""],  # empty new owner -> vanished
            path="/org/freedesktop/DBus",
        )
        client._handle_message(msg)

        assert client.connected is False
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        payload = ws.send_str.call_args.args[0]
        assert '"Disconnected"' in payload

    async def test_name_owner_changed_reappears_wakes_reconnect(self, client):
        await connected_client(client)

        client.connected = False
        client._on_name_owner_changed(["org.asamk.Signal", "", ":1.99"])

        assert client._reconnect_wake.is_set()

    async def test_unrelated_name_ignored(self, client):
        await connected_client(client)

        client._on_name_owner_changed(["org.other.Service", ":1.0", ""])
        assert client.connected is True


class TestNoteError:
    async def test_connection_error_marks_lost(self, client):
        client.connected = True
        client.note_error(DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "gone"))
        assert client.connected is False

    async def test_app_error_does_not_disconnect(self, client):
        client.connected = True
        client.note_error(DBusError("org.freedesktop.DBus.Error.InvalidArgs", "bad"))
        assert client.connected is True

    async def test_transport_error_marks_lost(self, client):
        client.connected = True
        client.note_error(BrokenPipeError("closed"))
        assert client.connected is False

    async def test_unknown_error_ignored(self, client):
        client.connected = True
        client.note_error(RuntimeError("weird"))
        assert client.connected is True


class TestInterface:
    async def test_interface_default(self, client):
        await connected_client(client)
        iface = client.interface(None)
        assert iface._path == "/org/asamk/Signal"
        assert iface._iface == "org.asamk.Signal"

    async def test_interface_per_account_cached(self, clients):
        config = Config(bus="session", host="localhost", port=9999, token=None, account=None, log_level="INFO", buffer_size=0)
        client = SignalClient(config, MagicMock(), clients)

        account_path = "/org/asamk/Signal/_491234567890"
        nodes = {"/org/asamk/Signal": make_node(_ROOT_MULTI_XML), account_path: make_node(_ROOT_SINGLE_XML)}
        bus = make_bus(nodes, {("/org/asamk/Signal", "listAccounts"): [[account_path]]})
        with patch("swb.dbus_client.MessageBus", return_value=bus):
            await client.connect()

        assert client.interface(None)._path == account_path
        other = client.interface("+499876543210")
        assert other._path == "/org/asamk/Signal/_499876543210"
        # Second lookup hits the cache
        assert client.interface("+499876543210") is other

    def test_interface_not_connected_raises(self, client):
        with pytest.raises(RuntimeError):
            client.interface(None)


class TestBroadcast:
    async def test_broadcast_to_clients(self, client, clients):
        ws = AsyncMock()
        clients.add(ws)
        client._broadcast({"signal": "Disconnected"})

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        ws.send_str.assert_called_once()
        assert '"Disconnected"' in ws.send_str.call_args.args[0]

    def test_broadcast_no_clients(self, client):
        client._broadcast({"signal": "Disconnected"})  # must not raise


class TestReconnect:
    async def test_reconnect_broadcasts_reconnected(self, client, clients):
        """After a successful non-initial connect, clients get Reconnected."""
        ws = AsyncMock()
        clients.add(ws)

        bus = await connected_client(client)
        client._initial_connect = False
        with patch("swb.dbus_client.MessageBus", return_value=bus):
            await client.connect()

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        payloads = [c.args[0] for c in ws.send_str.call_args_list]
        assert any('"Reconnected"' in p for p in payloads)

    async def test_subscribe_resubscribes_after_reconnect(self, client, clients):
        ws = AsyncMock()
        clients.add(ws)

        bus = await connected_client(client)
        client._initial_connect = False
        with patch("swb.dbus_client.MessageBus", return_value=bus):
            await client.connect()

        assert any(c[0] == "subscribeReceive" for c in bus.calls)


class TestWatchTransport:
    async def test_bus_disconnect_triggers_loss(self, client, clients):
        ws = AsyncMock()
        clients.add(ws)

        bus = await connected_client(client)

        # Simulate transport death
        bus._disconnect_event.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert client.connected is False
