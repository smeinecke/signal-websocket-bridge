"""Mock dbus module for testing without system dependencies."""

from unittest.mock import MagicMock


class MockDBus:
    """Mock dbus module."""

    class String:
        def __init__(self, val):
            self.val = val

        def __str__(self):
            return str(self.val)

        def __eq__(self, other):
            return str(self) == str(other)

        def __hash__(self):
            return hash(str(self.val))

    class Int64:
        def __init__(self, val):
            self.val = int(val)

        def __int__(self):
            return self.val

        def __eq__(self, other):
            return int(self) == int(other)

    class Int32:
        def __init__(self, val):
            self.val = int(val)

        def __int__(self):
            return self.val

    class UInt32:
        def __init__(self, val):
            self.val = int(val)

        def __int__(self):
            return self.val

    class UInt64:
        def __init__(self, val):
            self.val = int(val)

        def __int__(self):
            return self.val

    class Boolean:
        def __init__(self, val):
            self.val = bool(val)

        def __bool__(self):
            return self.val

        def __eq__(self, other):
            return bool(self) == bool(other)

    class Byte:
        def __init__(self, val):
            if isinstance(val, bytes):
                self.val = val[0] if val else 0
            else:
                self.val = int(val) & 0xFF

        def __int__(self):
            return self.val

        def __eq__(self, other):
            return int(self) == int(other)

    class Array(list):
        def __init__(self, iterable=None, signature=None):
            super().__init__(iterable or [])
            self.signature = signature

    class Struct(list):
        pass

    class Dictionary(dict):
        def items(self):
            return [(MockDBus.String(k) if isinstance(k, str) else k, MockDBus.String(v) if isinstance(v, str) else v) for k, v in super().items()]

    class ObjectPath:
        def __init__(self, path):
            self.path = path

        def __str__(self):
            return self.path

    class Signature:
        def __init__(self, sig):
            self.sig = sig

        def __str__(self):
            return self.sig

        def __eq__(self, other):
            return self.sig == other

        def __repr__(self):
            return f"Signature({self.sig!r})"

    class Interface:
        def __init__(self, obj, iface_name):
            self.obj = obj
            self.iface_name = iface_name

    class ProxyObject:
        pass

    class Bus:
        pass

    class exceptions:
        class DBusException(Exception):
            def get_dbus_name(self):
                return self.args[0] if self.args else ""

    @staticmethod
    def SystemBus():
        return MockDBus.Bus()

    @staticmethod
    def SessionBus():
        return MockDBus.Bus()

    class mainloop:
        class glib:
            @staticmethod
            def DBusGMainLoop(set_as_default=True):
                pass


# Create module-level classes
dbus = MockDBus()

# Allow importing individual classes
String = MockDBus.String
Int64 = MockDBus.Int64
Int32 = MockDBus.Int32
UInt32 = MockDBus.UInt32
UInt64 = MockDBus.UInt64
Boolean = MockDBus.Boolean
Byte = MockDBus.Byte
Array = MockDBus.Array
Struct = MockDBus.Struct
Dictionary = MockDBus.Dictionary
ObjectPath = MockDBus.ObjectPath
Signature = MockDBus.Signature
Interface = MockDBus.Interface
ProxyObject = MockDBus.ProxyObject
Bus = MockDBus.Bus
exceptions = MockDBus.exceptions
SystemBus = MockDBus.SystemBus
SessionBus = MockDBus.SessionBus
mainloop = MockDBus.mainloop
