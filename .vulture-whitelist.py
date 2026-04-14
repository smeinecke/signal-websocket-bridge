# Vulture whitelist for public API functions that appear unused but are intentionally exposed

from swb.dbus_client import is_connected

# Mark as used
is_connected
