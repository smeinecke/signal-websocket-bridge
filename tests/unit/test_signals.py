"""Tests for swb.signals module."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from swb.signals import _path_to_account, create_signal_handler, serialize_signal


def make_signal(member: str, body: list, path: str = "/org/asamk/Signal"):
    """Create a fake dbus-fast Message-like signal."""
    return SimpleNamespace(member=member, body=body, path=path)


class TestSerializeSignal:
    """Test signal serialization."""

    def test_message_received(self):
        """Test MessageReceived signal serialization."""
        args = [
            1234567890123,  # timestamp
            "+491234567890",  # sender
            b"group123",  # groupId (ay -> bytes)
            "Hello World",  # message
            ["/path/to/attachment"],  # attachments
        ]

        result = serialize_signal("MessageReceived", args)

        assert result["signal"] == "MessageReceived"
        assert result["timestamp"] == 1234567890123
        assert result["sender"] == "+491234567890"
        assert result["groupId"] == base64.b64encode(b"group123").decode()
        assert result["message"] == "Hello World"
        assert result["attachments"] == ["/path/to/attachment"]

    def test_message_received_empty_group(self):
        """Test MessageReceived with empty groupId."""
        args = [
            1234567890123,
            "+491234567890",
            b"",  # empty groupId
            "Direct message",
            [],
        ]

        result = serialize_signal("MessageReceived", args)

        assert result["groupId"] is None  # empty -> None

    def test_sync_message_received(self):
        """Test SyncMessageReceived signal serialization."""
        args = [
            1234567890123,  # timestamp
            "+491234567890",  # sender
            "+499876543210",  # destination
            b"group456",  # groupId
            "Sync message",  # message
            ["/path/attach"],  # attachments
        ]

        result = serialize_signal("SyncMessageReceived", args)

        assert result["signal"] == "SyncMessageReceived"
        assert result["timestamp"] == 1234567890123
        assert result["sender"] == "+491234567890"
        assert result["destination"] == "+499876543210"
        assert result["groupId"] == base64.b64encode(b"group456").decode()
        assert result["message"] == "Sync message"
        assert result["attachments"] == ["/path/attach"]

    def test_receipt_received(self):
        """Test ReceiptReceived signal serialization."""
        args = [1234567890123, "+491234567890"]

        result = serialize_signal("ReceiptReceived", args)

        assert result["signal"] == "ReceiptReceived"
        assert result["timestamp"] == 1234567890123
        assert result["sender"] == "+491234567890"

    def test_unknown_signal(self):
        """Test unknown signal falls back to generic format."""
        result = serialize_signal("UnknownSignal", ["test", 123])

        assert result["signal"] == "UnknownSignal"
        assert result["args"] == ["test", 123]

    def test_insufficient_args(self):
        """Test signal with insufficient args falls back to generic."""
        result = serialize_signal("MessageReceived", ["only one arg"])

        assert result["signal"] == "MessageReceived"
        assert "args" in result  # Falls back to generic


class TestCreateSignalHandler:
    """Test create_signal_handler function."""

    async def test_handler_broadcasts_to_clients(self):
        """Handler serializes the signal and sends it to each client."""
        clients = set()
        handler = create_signal_handler(clients)

        mock_ws = AsyncMock()
        clients.add(mock_ws)

        handler(make_signal("MessageReceived", [1, "+1", b"", "hi", []]))

        # send_str is scheduled via create_task; let it run
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_ws.send_str.assert_called_once()
        payload = json.loads(mock_ws.send_str.call_args.args[0])
        assert payload["signal"] == "MessageReceived"
        assert payload["message"] == "hi"
        assert "event_id" in payload

    async def test_handler_with_ws_send(self):
        """Handler falls back to ws.send when send_str is absent."""
        clients = set()
        handler = create_signal_handler(clients)

        mock_ws = AsyncMock()
        del mock_ws.send_str
        mock_ws.send = AsyncMock()
        clients.add(mock_ws)

        handler(make_signal("ReceiptReceived", [1, "+1"]))

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_ws.send.assert_called_once()

    async def test_handler_appends_to_event_buffer(self):
        """Serialized payloads are appended to the buffer before broadcast."""
        from collections import deque

        buf = deque(maxlen=10)
        handler = create_signal_handler(set(), buf)

        handler(make_signal("ReceiptReceived", [1, "+1"]))

        assert len(buf) == 1
        assert json.loads(buf[0])["signal"] == "ReceiptReceived"

    async def test_handler_no_buffer_when_none(self):
        """No buffering when event_buffer is None."""
        handler = create_signal_handler(set(), None)
        handler(make_signal("ReceiptReceived", [1, "+1"]))  # must not raise


class TestPathToAccount:
    """Test _path_to_account helper."""

    def test_account_path(self):
        assert _path_to_account("/org/asamk/Signal/_491234567890") == "+491234567890"

    def test_root_path_returns_none(self):
        assert _path_to_account("/org/asamk/Signal") is None

    def test_empty_path_returns_none(self):
        assert _path_to_account("") is None

    def test_international_number(self):
        assert _path_to_account("/org/asamk/Signal/_15555550100") == "+15555550100"


class TestSignalHandlerAccount:
    """Test that account is included in signal payloads from multi-account paths."""

    async def test_account_included_for_account_path(self):
        """handler() adds 'account' key when emitted from a per-account path."""
        clients = set()
        handler = create_signal_handler(clients)

        mock_ws = AsyncMock()
        clients.add(mock_ws)

        handler(
            make_signal(
                "MessageReceived",
                [1234567890, "+491234567890", b"", "Hello", []],
                path="/org/asamk/Signal/_491234567890",
            )
        )

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        payload = json.loads(mock_ws.send_str.call_args.args[0])
        assert payload["account"] == "+491234567890"

    def test_no_account_for_root_path(self):
        """No 'account' key when emitted from the root path (single-account mode)."""
        payload_dict = serialize_signal("ReceiptReceived", [1234567890, "+491234567890"])
        account = _path_to_account("/org/asamk/Signal")
        if account:
            payload_dict["account"] = account

        assert "account" not in payload_dict
