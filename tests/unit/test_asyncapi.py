"""Tests for swb.asyncapi module."""

from unittest.mock import MagicMock, patch

import pytest

dbus = pytest.importorskip("dbus")

from swb.asyncapi import (
    generate_asyncapi_spec,
    introspect_signal_interface,
)
from swb.config import Config


@pytest.fixture
def mock_signal_object():
    """Create a mock signal object."""
    return MagicMock()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    return Config(
        bus="system",
        host="localhost",
        port=8765,
        token=None,
        account=None,
        log_level="INFO",
        buffer_size=0,
    )


class TestIntrospectSignalInterface:
    """Test DBus introspection."""

    def test_introspect_returns_registry(self, mock_signal_object):
        """Test introspection returns method/signal registry."""
        # Mock the introspectable interface
        mock_introspectable = MagicMock()
        mock_introspectable.Introspect.return_value = """<?xml version="1.0" ?>
        <node>
            <interface name="org.asamk.Signal">
                <method name="sendMessage">
                    <arg direction="in" type="s" name="message"/>
                    <arg direction="in" type="as" name="attachments"/>
                    <arg direction="in" type="as" name="recipients"/>
                    <arg direction="out" type="x"/>
                </method>
                <method name="version">
                    <arg direction="out" type="s"/>
                </method>
                <signal name="MessageReceived">
                    <arg type="x" name="timestamp"/>
                    <arg type="s" name="sender"/>
                </signal>
            </interface>
        </node>"""
        mock_signal_object.GetInterface.return_value = mock_introspectable

        with patch("swb.asyncapi.ET"):
            registry = introspect_signal_interface(mock_signal_object)

        assert "methods" in registry
        assert "signals" in registry

    def test_introspect_caching(self, mock_signal_object):
        """Test introspection result is cached."""
        from swb.asyncapi import _introspection_cache

        # Clear cache first
        _introspection_cache.clear()

        # First call
        with patch.object(mock_signal_object, "GetInterface", side_effect=Exception("DBus error")):
            result1 = introspect_signal_interface(mock_signal_object)

        # Second call should return cached result
        result2 = introspect_signal_interface(mock_signal_object)

        assert result1 == result2


class TestGenerateAsyncapiSpec:
    """Test AsyncAPI spec generation."""

    def test_spec_structure(self, mock_config, mock_signal_object):
        """Test generated spec has correct structure."""
        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {
                "methods": {
                    "sendMessage": {
                        "args": [
                            {"name": "message", "type": "s", "schema": {"type": "string"}},
                        ],
                        "return_type": "x",
                        "return_schema": {"type": "integer"},
                    }
                },
                "signals": {
                    "MessageReceived": {
                        "args": [
                            {"name": "timestamp", "type": "x", "schema": {"type": "integer"}},
                        ]
                    }
                },
            }

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        assert spec["asyncapi"] == "2.6.0"
        assert "info" in spec
        assert "servers" in spec
        assert "channels" in spec
        assert "components" in spec
        assert "schemas" in spec["components"]

    def test_server_url(self, mock_config, mock_signal_object):
        """Test server URL is correct."""
        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {"methods": {}, "signals": {}}

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        assert spec["servers"]["production"]["url"] == "ws://localhost:8765/ws"
        assert spec["servers"]["production"]["protocol"] == "ws"

    def test_method_schemas(self, mock_config, mock_signal_object):
        """Test method request/response schemas are generated."""
        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {
                "methods": {
                    "sendMessage": {
                        "args": [
                            {"name": "message", "type": "s", "schema": {"type": "string"}},
                        ],
                        "return_type": "x",
                        "return_schema": {"type": "integer"},
                    }
                },
                "signals": {},
            }

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        assert "sendMessage_request" in spec["components"]["schemas"]
        assert "sendMessage_response" in spec["components"]["schemas"]

    def test_signal_schemas(self, mock_config, mock_signal_object):
        """Test signal schemas are generated."""
        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {
                "methods": {},
                "signals": {
                    "MessageReceived": {
                        "args": [
                            {"name": "timestamp", "type": "x", "schema": {"type": "integer"}},
                        ]
                    }
                },
            }

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        assert "MessageReceived_signal" in spec["components"]["schemas"]


class TestIntrospectSignalInterfaceRealXML:
    """Test DBus introspection with real XML parsing."""

    def test_introspect_real_xml(self, mock_signal_object):
        """Test introspection with real XML parsing."""
        from swb.asyncapi import _introspection_cache

        # Clear cache first
        _introspection_cache.clear()

        mock_introspectable = MagicMock()
        mock_introspectable.Introspect.return_value = """<?xml version="1.0" ?>
        <node>
            <interface name="org.asamk.Signal">
                <method name="sendMessage">
                    <arg direction="in" type="s" name="message"/>
                    <arg direction="in" type="as" name="attachments"/>
                    <arg direction="in" type="as" name="recipients"/>
                    <arg direction="out" type="x"/>
                </method>
                <method name="version">
                    <arg direction="out" type="s"/>
                </method>
                <signal name="MessageReceived">
                    <arg type="x" name="timestamp"/>
                    <arg type="s" name="sender"/>
                </signal>
                <signal name="UnknownSignal">
                    <arg type="s" name="data"/>
                </signal>
            </interface>
        </node>"""

        with patch("swb.asyncapi.dbus.Interface", return_value=mock_introspectable):
            from swb.asyncapi import introspect_signal_interface

            registry = introspect_signal_interface(mock_signal_object)

        assert "sendMessage" in registry["methods"]
        assert "version" in registry["methods"]
        assert "MessageReceived" in registry["signals"]
        assert "UnknownSignal" in registry["signals"]

    def test_introspect_exception_handling(self, mock_signal_object):
        """Test introspection exception handling."""
        from swb.asyncapi import _introspection_cache, introspect_signal_interface

        # Clear cache first
        _introspection_cache.clear()

        with patch("swb.asyncapi.dbus.Interface", side_effect=Exception("DBus error")):
            with patch("swb.asyncapi.logging") as mock_logging:
                registry = introspect_signal_interface(mock_signal_object)

        assert registry == {"methods": {}, "signals": {}}
        mock_logging.warning.assert_called()

    def test_introspect_cache_clear(self, mock_signal_object):
        """Test introspection cache can be cleared and repopulated."""
        from swb.asyncapi import _introspection_cache, introspect_signal_interface

        # Clear and populate cache
        _introspection_cache.clear()
        _introspection_cache["signal_interface"] = {"methods": {"cached": {}}, "signals": {}}

        registry = introspect_signal_interface(mock_signal_object)
        assert "cached" in registry["methods"]


class TestGenerateAsyncapiSpecExtended:
    """Extended AsyncAPI spec generation tests."""

    def test_known_signal_schema(self, mock_config, mock_signal_object):
        """Test that known signals use static schemas."""
        from swb.asyncapi import generate_asyncapi_spec

        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {
                "methods": {},
                "signals": {
                    "MessageReceived": {"args": []},
                    "SyncMessageReceived": {"args": []},
                    "ReceiptReceived": {"args": []},
                },
            }

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        # Known signals should have structured schemas
        assert "properties" in spec["components"]["schemas"]["MessageReceived_signal"]
        assert "properties" in spec["components"]["schemas"]["SyncMessageReceived_signal"]
        assert "properties" in spec["components"]["schemas"]["ReceiptReceived_signal"]

    def test_unknown_signal_fallback(self, mock_config, mock_signal_object):
        """Test unknown signals use generic fallback schema."""
        from swb.asyncapi import generate_asyncapi_spec

        with patch("swb.asyncapi.introspect_signal_interface") as mock_introspect:
            mock_introspect.return_value = {
                "methods": {},
                "signals": {
                    "CustomSignal": {"args": [{"name": "data", "type": "s", "schema": {"type": "string"}}]},
                },
            }

            spec = generate_asyncapi_spec(mock_config, mock_signal_object)

        # Unknown signal should have generic schema
        schema = spec["components"]["schemas"]["CustomSignal_signal"]
        assert schema["type"] == "object"
        assert "signal" in schema["properties"]
        assert "args" in schema["properties"]
