# Vulture whitelist for symbols that appear unused but are intentionally exposed
# (e.g. public API, entry points, framework hooks)

from swb.dbus_client import SignalClient

# Strong refs held to prevent asyncio task garbage collection
SignalClient._watch_task  # noqa: B018
# Set at connect time; read by tests and useful for diagnostics
SignalClient._object_path  # noqa: B018
SignalClient.single_account_mode  # noqa: B018
