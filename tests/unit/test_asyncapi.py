"""Tests for swb.asyncapi module."""

import pytest
from dbus_fast import introspection as intr

from swb.asyncapi import _extract_interface_data, generate_asyncapi_spec
from swb.config import Config


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


_BASIC_XML = """<?xml version="1.0" ?>
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

_CONTROL_XML = """<?xml version="1.0" ?>
<node>
    <interface name="org.asamk.SignalControl">
        <method name="listAccounts">
            <arg direction="out" type="ao"/>
        </method>
    </interface>
</node>"""


def make_node(xml: str):
    return intr.Node.parse(xml)


class TestExtractInterfaceData:
    """Test introspection Node -> registry conversion."""

    def test_returns_registry(self):
        registry = _extract_interface_data(make_node(_BASIC_XML))

        assert "methods" in registry
        assert "signals" in registry
        assert "sendMessage" in registry["methods"]
        assert "MessageReceived" in registry["signals"]

    def test_none_node_empty(self):
        registry = _extract_interface_data(None)
        assert registry == {"methods": {}, "signals": {}}

    def test_fallback_to_signal_control(self):
        """Falls back to SignalControl when org.asamk.Signal is absent."""
        registry = _extract_interface_data(make_node(_CONTROL_XML))
        assert "listAccounts" in registry["methods"]

    def test_method_args(self):
        registry = _extract_interface_data(make_node(_BASIC_XML))
        send = registry["methods"]["sendMessage"]

        arg_names = [a["name"] for a in send["args"]]
        assert arg_names == ["message", "attachments", "recipients"]
        assert send["return_type"] == "x"
        assert send["return_schema"] == {"type": "integer", "format": "int64"}

    def test_unnamed_args_get_indices(self):
        node = make_node("""<node><interface name="org.asamk.Signal">
            <method name="m"><arg direction="in" type="s"/><arg direction="in" type="i"/></method>
        </interface></node>""")
        registry = _extract_interface_data(node)
        names = [a["name"] for a in registry["methods"]["m"]["args"]]
        assert names == ["arg0", "arg1"]


class TestGenerateAsyncapiSpec:
    """Test AsyncAPI spec generation."""

    def test_spec_structure(self, mock_config):
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        assert spec["asyncapi"] == "2.6.0"
        assert "info" in spec
        assert "servers" in spec
        assert "channels" in spec
        assert "components" in spec
        assert "schemas" in spec["components"]

    def test_server_url(self, mock_config):
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        assert spec["servers"]["production"]["url"] == "ws://localhost:8765/ws"
        assert spec["servers"]["production"]["protocol"] == "ws"

    def test_method_schemas(self, mock_config):
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        assert "sendMessage_request" in spec["components"]["schemas"]
        assert "sendMessage_response" in spec["components"]["schemas"]

        req = spec["components"]["schemas"]["sendMessage_request"]
        assert req["properties"]["method"]["const"] == "sendMessage"
        params = req["properties"]["params"]
        assert "message" in params["properties"]
        assert "message" in params["required"]

    def test_signal_schemas(self, mock_config):
        """Test signal schemas are generated."""
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        assert "MessageReceived_signal" in spec["components"]["schemas"]

    def test_known_signal_named_fields(self, mock_config):
        """Known signals use the static named-field schema."""
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        schema = spec["components"]["schemas"]["MessageReceived_signal"]
        assert "sender" in schema["properties"]
        assert "groupId" in schema["properties"]

    def test_unknown_signal_generic_fallback(self, mock_config):
        """Unknown signals use the {signal, args[]} fallback schema."""
        spec = generate_asyncapi_spec(mock_config, make_node(_BASIC_XML))

        schema = spec["components"]["schemas"]["UnknownSignal_signal"]
        assert schema["properties"]["args"]["type"] == "array"

    def test_empty_spec_when_no_node(self, mock_config):
        """No introspection (not connected) yields an empty spec skeleton."""
        spec = generate_asyncapi_spec(mock_config, None)

        assert spec["asyncapi"] == "2.6.0"
        assert spec["components"]["schemas"] == {}
