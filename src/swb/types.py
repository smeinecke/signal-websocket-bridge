"""Type conversion helpers between DBus and Python/JSON."""

import base64
import os
from pathlib import Path

import dbus


def dbus_to_native(val):
    """Recursively convert dbus types to plain Python for JSON serialization.

    ay (byte arrays) → base64 strings.
    Structs → lists (caller can reshape as needed).
    """
    if isinstance(val, dbus.String):
        return str(val)
    if isinstance(val, (dbus.Int64, dbus.Int32, dbus.UInt32, dbus.UInt64)):
        return int(val)
    if isinstance(val, dbus.Boolean):
        return bool(val)
    if isinstance(val, dbus.Byte):
        return int(val)
    if isinstance(val, dbus.Array):
        # ay → base64 string
        sig = getattr(val, "signature", None)
        if sig == "y" or (val and isinstance(val[0], dbus.Byte)):
            return base64.b64encode(bytes(int(b) for b in val)).decode()
        return [dbus_to_native(v) for v in val]
    if isinstance(val, dbus.Struct):
        return [dbus_to_native(v) for v in val]
    if isinstance(val, dbus.Dictionary):
        return {dbus_to_native(k): dbus_to_native(v) for k, v in val.items()}
    return val


def to_bytes(s: str) -> dbus.Array:
    """base64 string → dbus byte array (ay). Used for groupId, receipt, etc."""
    raw = base64.b64decode(s)
    return dbus.Array([dbus.Byte(b) for b in raw], signature=dbus.Signature("y"))


def to_int64(v) -> dbus.Int64:
    return dbus.Int64(int(v))


def to_int64_array(lst: list) -> dbus.Array:
    return dbus.Array([dbus.Int64(int(v)) for v in lst], signature=dbus.Signature("x"))


def to_string_array(lst: list) -> dbus.Array:
    """Convert list of strings to dbus Array of strings (as signature)."""
    return dbus.Array(lst, signature=dbus.Signature("s"))


def validate_attachments(attachments: list[str]) -> None:
    """Validate attachment paths exist and are readable."""
    for path in attachments:
        p = Path(path)
        if not p.exists():
            raise ValueError(f"attachment not found: {path}")
        if not p.is_file():
            raise ValueError(f"attachment is not a file: {path}")
        if not os.access(p, os.R_OK):
            raise ValueError(f"attachment not readable: {path}")


# DBus type → JSON Schema mapping
_DBUS_TO_JSON_SCHEMA: dict[str, dict] = {
    "s": {"type": "string"},
    "i": {"type": "integer"},
    "x": {"type": "integer", "format": "int64"},
    "b": {"type": "boolean"},
    "y": {"type": "integer", "minimum": 0, "maximum": 255},
    "as": {"type": "array", "items": {"type": "string"}},
    "ax": {"type": "array", "items": {"type": "integer", "format": "int64"}},
    "ab": {"type": "array", "items": {"type": "boolean"}},
    "ay": {"type": "string", "format": "base64", "description": "Byte array encoded as base64 (groupId, receipt)"},
    "t": {"type": "integer", "format": "int64"},  # UInt64 timestamp
}


def dbus_signature_to_json_schema(sig: str) -> dict:
    """Convert DBus signature to JSON Schema."""
    # Simple types
    if sig in _DBUS_TO_JSON_SCHEMA:
        return _DBUS_TO_JSON_SCHEMA[sig].copy()

    # Array of simple types
    if sig.startswith("a") and len(sig) == 2:
        elem_sig = sig[1]
        if elem_sig in _DBUS_TO_JSON_SCHEMA:
            return {"type": "array", "items": _DBUS_TO_JSON_SCHEMA[elem_sig].copy()}

    # Struct (tuples from listGroups, listDevices, etc)
    if sig.startswith("(") and sig.endswith(")"):
        # Return generic array - caller reshapes
        return {"type": "array", "items": {}}

    # Array of structs
    if sig.startswith("a(") and sig.endswith(")"):
        return {"type": "array", "items": {"type": "array", "items": {}}}

    # Object path
    if sig == "o":
        return {"type": "string", "format": "uri"}

    # Default fallback
    return {"type": "object"}
