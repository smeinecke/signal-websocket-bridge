"""Tests for swb.types module."""

import base64
from pathlib import Path
from unittest.mock import patch

import pytest

dbus = pytest.importorskip("dbus")

from swb.types import (
    dbus_signature_to_json_schema,
    dbus_to_native,
    to_bytes,
    to_int64,
    to_int64_array,
    validate_attachments,
)


class TestDbusToNative:
    """Test DBus to native Python conversion."""

    def test_string(self):
        """Test dbus.String conversion."""
        result = dbus_to_native(dbus.String("hello"))
        assert result == "hello"
        assert isinstance(result, str)

    def test_int64(self):
        """Test dbus.Int64 conversion."""
        result = dbus_to_native(dbus.Int64(1234567890123))
        assert result == 1234567890123
        assert isinstance(result, int)

    def test_int32(self):
        """Test dbus.Int32 conversion."""
        result = dbus_to_native(dbus.Int32(42))
        assert result == 42
        assert isinstance(result, int)

    def test_boolean(self):
        """Test dbus.Boolean conversion."""
        result = dbus_to_native(dbus.Boolean(True))
        assert result is True
        assert isinstance(result, bool)

    def test_byte(self):
        """Test dbus.Byte conversion."""
        result = dbus_to_native(dbus.Byte(255))
        assert result == 255
        assert isinstance(result, int)

    def test_byte_array_to_base64(self):
        """Test byte array (ay) conversion to base64."""
        byte_array = dbus.Array([dbus.Byte(b) for b in b"hello"], signature="y")
        result = dbus_to_native(byte_array)
        assert result == base64.b64encode(b"hello").decode()

    def test_string_array(self):
        """Test string array conversion."""
        arr = dbus.Array([dbus.String("a"), dbus.String("b")], signature="s")
        result = dbus_to_native(arr)
        assert result == ["a", "b"]

    def test_struct(self):
        """Test struct conversion."""
        struct = dbus.Struct([dbus.String("test"), dbus.Int64(123)])
        result = dbus_to_native(struct)
        assert result == ["test", 123]

    def test_dictionary(self):
        """Test dictionary conversion."""
        d = dbus.Dictionary({dbus.String("key"): dbus.String("value")})
        result = dbus_to_native(d)
        assert result == {"key": "value"}


class TestToBytes:
    """Test base64 to bytes conversion."""

    def test_base64_to_bytes(self):
        """Test base64 string to dbus byte array."""
        original = b"test data"
        b64 = base64.b64encode(original).decode()
        result = to_bytes(b64)

        assert isinstance(result, dbus.Array)
        assert result.signature == "y"
        assert bytes(int(b) for b in result) == original


class TestToInt64:
    """Test int64 conversion."""

    def test_int_to_int64(self):
        """Test integer to dbus.Int64."""
        result = to_int64(1234567890123)
        assert isinstance(result, dbus.Int64)
        assert int(result) == 1234567890123


class TestToInt64Array:
    """Test int64 array conversion."""

    def test_list_to_int64_array(self):
        """Test list of integers to dbus int64 array."""
        result = to_int64_array([1, 2, 3])
        assert isinstance(result, dbus.Array)
        assert result.signature == "x"
        assert [int(x) for x in result] == [1, 2, 3]


class TestValidateAttachments:
    """Test attachment validation."""

    def test_valid_attachments(self, tmp_path):
        """Test valid attachment paths."""
        file1 = tmp_path / "test1.txt"
        file2 = tmp_path / "test2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        # Should not raise
        validate_attachments([str(file1), str(file2)])

    def test_nonexistent_file(self, tmp_path):
        """Test nonexistent file raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            validate_attachments([str(tmp_path / "nonexistent.txt")])

    def test_directory_not_file(self, tmp_path):
        """Test directory raises ValueError."""
        with pytest.raises(ValueError, match="not a file"):
            validate_attachments([str(tmp_path)])


class TestDbusSignatureToJsonSchema:
    """Test DBus signature to JSON Schema conversion."""

    def test_string_signature(self):
        """Test 's' signature."""
        result = dbus_signature_to_json_schema("s")
        assert result == {"type": "string"}

    def test_int_signature(self):
        """Test 'i' signature."""
        result = dbus_signature_to_json_schema("i")
        assert result == {"type": "integer"}

    def test_int64_signature(self):
        """Test 'x' signature."""
        result = dbus_signature_to_json_schema("x")
        assert result == {"type": "integer", "format": "int64"}

    def test_boolean_signature(self):
        """Test 'b' signature."""
        result = dbus_signature_to_json_schema("b")
        assert result == {"type": "boolean"}

    def test_byte_array_signature(self):
        """Test 'ay' signature (base64)."""
        result = dbus_signature_to_json_schema("ay")
        assert result["type"] == "string"
        assert result["format"] == "base64"

    def test_string_array_signature(self):
        """Test 'as' signature."""
        result = dbus_signature_to_json_schema("as")
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_object_path_signature(self):
        """Test 'o' signature."""
        result = dbus_signature_to_json_schema("o")
        assert result["type"] == "string"
        assert result["format"] == "uri"

    def test_unknown_signature(self):
        """Test unknown signature defaults to object."""
        result = dbus_signature_to_json_schema("unknown")
        assert result == {"type": "object"}
