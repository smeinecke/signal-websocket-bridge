"""Tests for swb.types module."""

import base64

import pytest
from dbus_fast import Variant

from swb.types import (
    dbus_signature_to_json_schema,
    dbus_to_native,
    to_bytes,
    to_int64,
    to_int64_array,
    to_string_array,
    validate_attachments,
)


class TestDbusToNative:
    """Test DBus to native Python conversion."""

    def test_string_passthrough(self):
        result = dbus_to_native("hello")
        assert result == "hello"
        assert isinstance(result, str)

    def test_int64(self):
        result = dbus_to_native(1234567890123)
        assert result == 1234567890123
        assert isinstance(result, int)

    def test_int32(self):
        result = dbus_to_native(42)
        assert result == 42
        assert isinstance(result, int)

    def test_boolean(self):
        result = dbus_to_native(True)
        assert result is True
        assert isinstance(result, bool)

    def test_byte(self):
        result = dbus_to_native(255)
        assert result == 255
        assert isinstance(result, int)

    def test_byte_array_to_base64(self):
        """ay arrives as bytes from dbus-fast -> base64 string."""
        result = dbus_to_native(b"hello")
        assert result == base64.b64encode(b"hello").decode()

    def test_bytearray_to_base64(self):
        result = dbus_to_native(bytearray(b"hi"))
        assert result == base64.b64encode(b"hi").decode()

    def test_empty_byte_array(self):
        result = dbus_to_native(b"")
        assert result == ""

    def test_variant_unwrapped(self):
        result = dbus_to_native(Variant("s", "wrapped"))
        assert result == "wrapped"

    def test_variant_byte_array(self):
        result = dbus_to_native(Variant("ay", b"data"))
        assert result == base64.b64encode(b"data").decode()

    def test_string_array(self):
        result = dbus_to_native(["a", "b"])
        assert result == ["a", "b"]

    def test_struct_as_list(self):
        result = dbus_to_native(("test", 123))
        assert result == ["test", 123]

    def test_dictionary(self):
        result = dbus_to_native({"key": "value"})
        assert result == {"key": "value"}

    def test_nested_containers(self):
        result = dbus_to_native({"items": [b"\x01", ["a"]]})
        assert result == {"items": [base64.b64encode(b"\x01").decode(), ["a"]]}


class TestToBytes:
    """Test base64 to bytes conversion."""

    def test_base64_to_bytes(self):
        original = b"test data"
        b64 = base64.b64encode(original).decode()
        result = to_bytes(b64)

        assert result == original
        assert isinstance(result, bytes)


class TestToInt64:
    """Test int64 conversion."""

    def test_int_to_int64(self):
        result = to_int64(1234567890123)
        assert result == 1234567890123
        assert isinstance(result, int)


class TestToInt64Array:
    """Test int64 array conversion."""

    def test_list_to_int64_array(self):
        result = to_int64_array([1, 2, 3])
        assert result == [1, 2, 3]
        assert all(isinstance(x, int) for x in result)


class TestToStringArray:
    """Test string array conversion."""

    def test_list(self):
        assert to_string_array(["a", "b"]) == ["a", "b"]
        assert to_string_array([]) == []


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

    def test_attachment_not_readable(self, tmp_path):
        """Test unreadable file raises ValueError."""
        file1 = tmp_path / "test1.txt"
        file1.write_text("content1")
        # Remove read permission
        file1.chmod(0o000)

        try:
            with pytest.raises(ValueError, match="not readable"):
                validate_attachments([str(file1)])
        finally:
            # Restore permissions for cleanup
            file1.chmod(0o644)


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
        assert result == {"type": "string", "format": "uri"}

    def test_unknown_signature(self):
        """Test unknown signature defaults to object."""
        result = dbus_signature_to_json_schema("unknown")
        assert result == {"type": "object"}

    def test_struct_signature(self):
        """Test struct signature (tuple)."""
        result = dbus_signature_to_json_schema("(ss)")
        assert result == {"type": "array", "items": {}}

    def test_array_of_structs_signature(self):
        """Test array of structs signature."""
        result = dbus_signature_to_json_schema("a(ss)")
        assert result == {"type": "array", "items": {"type": "array", "items": {}}}
