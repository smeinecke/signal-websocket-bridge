"""Tests for swb.signals module."""

import base64

import pytest

dbus = pytest.importorskip("dbus")

from swb.signals import serialize_signal


class TestSerializeSignal:
    """Test signal serialization."""

    def test_message_received(self):
        """Test MessageReceived signal serialization."""
        args = (
            dbus.Int64(1234567890123),  # timestamp
            dbus.String("+491234567890"),  # sender
            dbus.Array([dbus.Byte(b) for b in b"group123"], signature="y"),  # groupId
            dbus.String("Hello World"),  # message
            dbus.Array([dbus.String("/path/to/attachment")]),  # attachments
        )

        result = serialize_signal("MessageReceived", args)

        assert result["signal"] == "MessageReceived"
        assert result["timestamp"] == 1234567890123
        assert result["sender"] == "+491234567890"
        assert result["groupId"] == base64.b64encode(b"group123").decode()
        assert result["message"] == "Hello World"
        assert result["attachments"] == ["/path/to/attachment"]

    def test_message_received_empty_group(self):
        """Test MessageReceived with empty groupId."""
        args = (
            dbus.Int64(1234567890123),
            dbus.String("+491234567890"),
            dbus.Array([], signature="y"),  # empty groupId
            dbus.String("Direct message"),
            dbus.Array([], signature="s"),
        )

        result = serialize_signal("MessageReceived", args)

        assert result["groupId"] is None  # empty -> None

    def test_sync_message_received(self):
        """Test SyncMessageReceived signal serialization."""
        args = (
            dbus.Int64(1234567890123),  # timestamp
            dbus.String("+491234567890"),  # sender
            dbus.String("+499876543210"),  # destination
            dbus.Array([dbus.Byte(b) for b in b"group456"], signature="y"),  # groupId
            dbus.String("Sync message"),  # message
            dbus.Array([dbus.String("/path/attach")]),  # attachments
        )

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
        args = (
            dbus.Int64(1234567890123),  # timestamp
            dbus.String("+491234567890"),  # sender
        )

        result = serialize_signal("ReceiptReceived", args)

        assert result["signal"] == "ReceiptReceived"
        assert result["timestamp"] == 1234567890123
        assert result["sender"] == "+491234567890"

    def test_unknown_signal(self):
        """Test unknown signal falls back to generic format."""
        args = (dbus.String("test"), dbus.Int64(123))

        result = serialize_signal("UnknownSignal", args)

        assert result["signal"] == "UnknownSignal"
        assert result["args"] == ["test", 123]

    def test_insufficient_args(self):
        """Test signal with insufficient args falls back to generic."""
        args = (dbus.String("only one arg"),)

        result = serialize_signal("MessageReceived", args)

        assert result["signal"] == "MessageReceived"
        assert "args" in result  # Falls back to generic
