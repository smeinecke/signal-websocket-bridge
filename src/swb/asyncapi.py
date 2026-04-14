"""AsyncAPI specification generation from DBus introspection."""

import logging
from typing import Any

import dbus
from defusedxml import ElementTree as ET

from swb.config import Config
from swb.types import dbus_signature_to_json_schema

# Cache for introspected interface
_introspection_cache: dict[str, Any] = {}

# Static schemas for the three known signals, matching the named-field payloads
# emitted by signals.py (serialize_signal). Unknown signals fall back to {signal, args[]}.
_KNOWN_SIGNAL_SCHEMAS: dict[str, dict] = {
    "MessageReceived": {
        "properties": {
            "signal": {"type": "string", "const": "MessageReceived"},
            "timestamp": {"type": "integer", "format": "int64", "description": "Milliseconds since epoch"},
            "sender": {"type": "string", "description": "Sender phone number"},
            "groupId": {"type": "string", "format": "base64", "nullable": True, "description": "null for direct messages"},
            "message": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}, "description": "Local file paths"},
        },
        "required": ["signal", "timestamp", "sender", "groupId", "message", "attachments"],
    },
    "SyncMessageReceived": {
        "properties": {
            "signal": {"type": "string", "const": "SyncMessageReceived"},
            "timestamp": {"type": "integer", "format": "int64"},
            "sender": {"type": "string"},
            "destination": {"type": "string", "description": "Recipient number or group"},
            "groupId": {"type": "string", "format": "base64", "nullable": True},
            "message": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["signal", "timestamp", "sender", "destination", "groupId", "message", "attachments"],
    },
    "ReceiptReceived": {
        "properties": {
            "signal": {"type": "string", "const": "ReceiptReceived"},
            "timestamp": {"type": "integer", "format": "int64"},
            "sender": {"type": "string"},
        },
        "required": ["signal", "timestamp", "sender"],
    },
}


def _parse_method_args(method) -> tuple[list[dict], str | None, dict | None]:
    """Extract input args, output type and schema from a method element."""
    in_args: list[dict] = []
    out_type: str | None = None
    out_schema: dict | None = None

    for arg in method.findall("arg"):
        direction = arg.get("direction", "in")
        sig = arg.get("type", "")
        if direction == "in":
            in_args.append({
                "name": arg.get("name", f"arg{len(in_args)}"),
                "type": sig,
                "schema": dbus_signature_to_json_schema(sig),
            })
        elif direction == "out":
            out_type = sig
            out_schema = dbus_signature_to_json_schema(sig)

    return in_args, out_type, out_schema


def _register_method(registry: dict, name: str, in_args: list, out_type: str | None, out_schema: dict | None) -> None:
    """Register method, keeping the variant with most parameters for overloaded methods."""
    existing = registry["methods"].get(name)
    if existing is None or len(in_args) > len(existing["args"]):
        registry["methods"][name] = {
            "args": in_args,
            "return_type": out_type,
            "return_schema": out_schema or {"type": "null"},
        }


def _parse_signal_args(signal) -> list[dict]:
    """Extract arguments from a signal element."""
    args = []
    for arg in signal.findall("arg"):
        sig = arg.get("type", "")
        args.append({
            "name": arg.get("name", f"arg{len(args)}"),
            "type": sig,
            "schema": dbus_signature_to_json_schema(sig),
        })
    return args


def _extract_interface_data(root) -> dict[str, Any]:
    """Parse XML root and extract methods and signals from org.asamk.Signal interface."""
    registry: dict[str, Any] = {"methods": {}, "signals": {}}

    for interface in root.findall(".//interface"):
        if interface.get("name") != "org.asamk.Signal":
            continue

        # --- Methods ---
        for method in interface.findall("method"):
            name = method.get("name", "")
            if not name:
                continue
            in_args, out_type, out_schema = _parse_method_args(method)
            _register_method(registry, name, in_args, out_type, out_schema)

        # --- Signals ---
        for signal in interface.findall("signal"):
            name = signal.get("name", "")
            if not name:
                continue
            registry["signals"][name] = {"args": _parse_signal_args(signal)}

    return registry


def introspect_signal_interface(signal_object) -> dict[str, Any]:
    """Introspect org.asamk.Signal interface and return method registry."""
    if "signal_interface" in _introspection_cache:
        return _introspection_cache["signal_interface"]

    try:
        introspectable = dbus.Interface(signal_object, "org.freedesktop.DBus.Introspectable")
        xml_str = introspectable.Introspect()
        root = ET.fromstring(xml_str)
        registry = _extract_interface_data(root)
        _introspection_cache["signal_interface"] = registry
        return registry

    except Exception as exc:
        logging.warning(f"Could not introspect DBus interface: {exc}")
        return {"methods": {}, "signals": {}}


def generate_asyncapi_spec(config: Config, signal_object) -> dict[str, Any]:
    """Generate AsyncAPI 2.6 spec from introspected DBus interface."""
    registry = introspect_signal_interface(signal_object)

    schemas: dict[str, Any] = {}
    messages: dict[str, Any] = {}

    # --- Method request/response schemas ---
    for method_name, method_info in registry.get("methods", {}).items():
        req_properties: dict[str, Any] = {}
        req_required: list[str] = []
        _optional = {"avatar", "members", "attachments", "stop", "remove", "familyName"}

        for arg in method_info.get("args", []):
            arg_name = arg["name"]
            req_properties[arg_name] = arg["schema"]
            if arg_name not in _optional:
                req_required.append(arg_name)

        schemas[f"{method_name}_request"] = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "method": {"type": "string", "const": method_name},
                "params": {
                    "type": "object",
                    "properties": req_properties,
                    "required": req_required,
                },
            },
            "required": ["method", "params"],
        }

        schemas[f"{method_name}_response"] = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "result": method_info.get("return_schema", {"type": "null"}),
            },
            "required": ["result"],
        }

        messages[method_name] = {
            "name": method_name,
            "contentType": "application/json",
            "payload": {"$ref": f"#/components/schemas/{method_name}_request"},
        }

    # --- Signal schemas ---
    for signal_name, signal_info in registry.get("signals", {}).items():
        if signal_name in _KNOWN_SIGNAL_SCHEMAS:
            # Use static named-field schema matching signals.py output
            schemas[f"{signal_name}_signal"] = {
                "type": "object",
                **_KNOWN_SIGNAL_SCHEMAS[signal_name],
            }
        else:
            # Unknown signal: generic {signal, args[]} fallback
            args_schemas = []
            for i, arg in enumerate(signal_info.get("args", [])):
                args_schemas.append(arg.get("schema", {}))

            schemas[f"{signal_name}_signal"] = {
                "type": "object",
                "properties": {
                    "signal": {"type": "string", "const": signal_name},
                    "args": {"type": "array", "items": args_schemas or {}},
                },
                "required": ["signal", "args"],
            }

    # --- Full AsyncAPI spec ---
    return {
        "asyncapi": "2.6.0",
        "info": {
            "title": "signal-cli WebSocket Bridge",
            "version": "auto-generated",
            "description": (
                "Auto-generated AsyncAPI specification from DBus introspection. "
                "groupId fields are base64-encoded byte arrays. "
                "Timestamps are int64 milliseconds since epoch."
            ),
        },
        "servers": {
            "production": {
                "url": f"ws://{config.host}:{config.port}/ws",
                "protocol": "ws",
            }
        },
        "channels": {
            "/ws": {
                "description": "WebSocket endpoint for JSON-RPC calls and DBus signal subscriptions",
                "subscribe": {"message": {"oneOf": [{"$ref": f"#/components/messages/{m}"} for m in messages]}},
                "publish": {
                    "message": {
                        "oneOf": (
                            [{"$ref": f"#/components/schemas/{m}_response"} for m in registry.get("methods", {})]
                            + [{"$ref": f"#/components/schemas/{s}_signal"} for s in registry.get("signals", {})]
                        )
                    }
                },
            }
        },
        "components": {
            "schemas": schemas,
            "messages": messages,
        },
    }
