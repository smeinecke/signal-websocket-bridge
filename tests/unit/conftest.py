"""Pytest configuration for unit tests."""

import sys
import types
from pathlib import Path

# Add the tests/unit directory to path to allow importing our mock
test_dir = Path(__file__).parent

# Inject mock dbus before any imports
try:
    import dbus
except ImportError:
    # Use our mock dbus module
    from tests.unit import dbus_mock

    # Create proper module types
    dbus_mod = types.ModuleType("dbus")
    for attr_name in dir(dbus_mock.dbus):
        if not attr_name.startswith("__"):
            setattr(dbus_mod, attr_name, getattr(dbus_mock.dbus, attr_name))

    sys.modules["dbus"] = dbus_mod

    # Also need to mock dbus.mainloop.glib
    mainloop_mod = types.ModuleType("dbus.mainloop")
    glib_mod = types.ModuleType("dbus.mainloop.glib")
    glib_mod.DBusGMainLoop = dbus_mock.dbus.mainloop.glib.DBusGMainLoop
    mainloop_mod.glib = glib_mod
    sys.modules["dbus.mainloop"] = mainloop_mod
    sys.modules["dbus.mainloop.glib"] = glib_mod

    # Mock gi.repository.GLib
    gi_mod = types.ModuleType("gi")
    repository_mod = types.ModuleType("gi.repository")

    class MockGLib:
        class MainLoop:
            def run(self):
                pass

            def quit(self):
                pass

    repository_mod.GLib = MockGLib
    gi_mod.repository = repository_mod
    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = repository_mod
    sys.modules["gi.repository.GLib"] = MockGLib
