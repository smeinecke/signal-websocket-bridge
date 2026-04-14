# signalbot

A WebSocket bridge for signal-cli that exposes incoming Signal messages as push events (via DBus) and allows sending messages via a simple JSON-RPC interface.

## Architecture

```
Signal Network
     │
signal-cli (DBus daemon)
     │  DBus signals (push, no polling)
signalbotcli-websocket.py
     │  WebSocket (JSON)
Your application / bot
```

Incoming messages are pushed to all connected WebSocket clients the moment signal-cli fires a DBus signal — no polling involved.

## Docker

A ready-to-use Docker image is available on GitHub Container Registry. The image includes:

- **Python 3.13** with the WebSocket bridge
- **signal-cli 0.14.2** with OpenJDK
- **DBus** for communication between components

### Supported platforms

- `linux/amd64` (x86_64)
- `linux/arm/v7` (ARMv7 - Raspberry Pi 2/3)
- `linux/arm64/v8` (ARM64 - Raspberry Pi 4, Apple Silicon)

### Quick start

```bash
# Pull the image
docker pull ghcr.io/smeinecke/signal-websocket-bridge:latest

# Run with docker-compose (recommended)
docker compose up -d
```

### Docker Compose example

See `docker-compose.yml`:

```yaml
services:
  signal-bridge:
    image: ghcr.io/smeinecke/signal-websocket-bridge:latest
    environment:
      - SIGNAL_WS_HOST=0.0.0.0
      - SIGNAL_WS_PORT=8765
      - SIGNAL_WS_TOKEN=your-secret-token
      - SIGNAL_ACCOUNT=+4915...
    volumes:
      - signal-cli-data:/var/lib/signal-cli
      - /run/dbus:/run/dbus:ro
    ports:
      - "8765:8765"
    privileged: true

volumes:
  signal-cli-data:
```

### Building locally

```bash
# Clone the repository
git clone https://github.com/smeinecke/signal-websocket-bridge.git
cd signal-websocket-bridge

# Build the image
make docker-build

# Or manually
docker build -t signal-websocket-bridge:local .
```

### Base images

- **Builder & Runtime**: `python:3.13-slim-trixie` (Debian 13)
- **Java**: `default-jre-headless` (OpenJDK from Debian repos)

## Prerequisites (non-Docker)

### 1. System packages (cannot be installed via pip)

```bash
# Debian / Ubuntu
sudo apt install python3-dbus python3-gi

# Arch
sudo pacman -S python-dbus python-gobject
```

### 2. Python dependencies

```bash
uv sync
# or: pip install websockets
```

### 3. signal-cli running in DBus daemon mode

signal-cli must be started as a DBus service so that `org.asamk.Signal` is available on the system bus:

```bash
# Register your account first (one-time)
./signal-cli-0.14.2/bin/signal-cli -a +49... register
./signal-cli-0.14.2/bin/signal-cli -a +49... verify <code>

# Start the DBus daemon
./signal-cli-0.14.2/bin/signal-cli -a +49... daemon --system
```

For autostart, install the provided systemd service or DBus activation file from the signal-cli docs.

## Running the bridge

```bash
# Default: system bus, localhost:8765
python signalbotcli-websocket.py

# Per-user signal-cli install (session bus)
python signalbotcli-websocket.py --session

# Custom host/port
python signalbotcli-websocket.py --host 0.0.0.0 --port 9000

# Via environment variables
SIGNAL_DBUS_BUS=session SIGNAL_WS_HOST=0.0.0.0 SIGNAL_WS_PORT=9000 python signalbotcli-websocket.py
```

> **System vs session bus**: signal-cli started as a systemd service or with `--system`
> uses the system bus. A user-level install (e.g. `signal-cli daemon` without `--system`)
> uses the session bus. When in doubt, check with:
> ```bash
> dbus-send --system --print-reply --dest=org.asamk.Signal /org/asamk/Signal org.freedesktop.DBus.Introspectable.Introspect
> # if that fails, try --session instead of --system
> ```

## WebSocket protocol

### Receiving messages (server → client, push)

Every DBus signal from `org.asamk.Signal` is forwarded as JSON:

```json
{
  "signal": "MessageReceived",
  "args": [1713000000000, "+4915100000000", [], "Hello!", []]
}
```

Signal argument layout for `MessageReceived`:
| Index | Type | Description |
|-------|------|-------------|
| 0 | int | Timestamp (ms) |
| 1 | string | Sender number |
| 2 | array | Group ID (empty for 1:1) |
| 3 | string | Message text |
| 4 | array | Attachment paths |

Other signals you may receive: `ReceiptReceived`, `SyncMessageReceived`, `ContactsUpdated`, etc.

### Sending messages (client → server, request/response)

#### Send a 1:1 message

```json
{
  "id": 1,
  "method": "sendMessage",
  "params": {
    "message": "Hello from the bot!",
    "recipients": ["+4915100000000"]
  }
}
```

Response:
```json
{"id": 1, "result": "ok"}
```

#### Send a group message

```json
{
  "id": 2,
  "method": "sendGroupMessage",
  "params": {
    "message": "Hello group!",
    "groupId": "base64groupid=="
  }
}
```

#### With attachments

```json
{
  "id": 3,
  "method": "sendMessage",
  "params": {
    "message": "See attached",
    "recipients": ["+4915100000000"],
    "attachments": ["/tmp/photo.jpg"]
  }
}
```

### Full method reference

`groupId` fields always use **base64-encoded strings** in JSON (decoded to `ay` byte arrays before the DBus call). Timestamps are milliseconds since epoch.

#### Messaging

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `sendMessage` | `message`, `recipients[]` | `attachments[]` | `{timestamp}` |
| `sendNoteToSelfMessage` | `message` | `attachments[]` | `{timestamp}` |
| `sendMessageReaction` | `emoji`, `remove`, `targetAuthor`, `targetSentTimestamp`, `recipients[]` | — | `{timestamp}` |
| `sendReadReceipt` | `recipient`, `targetSentTimestamps[]` | — | null |
| `sendViewedReceipt` | `recipient`, `targetSentTimestamps[]` | — | null |
| `sendTyping` | `recipient` | `stop` (default false) | null |
| `sendRemoteDeleteMessage` | `targetSentTimestamp`, `recipients[]` | — | `{timestamp}` |
| `sendEndSessionMessage` | `recipients[]` | — | null |
| `sendPaymentNotification` | `receipt` (base64), `note`, `recipient` | — | `{timestamp}` |

#### Groups

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `sendGroupMessage` | `message`, `groupId` | `attachments[]` | `{timestamp}` |
| `sendGroupMessageReaction` | `emoji`, `remove`, `targetAuthor`, `targetSentTimestamp`, `groupId` | — | `{timestamp}` |
| `sendGroupRemoteDeleteMessage` | `targetSentTimestamp`, `groupId` | — | `{timestamp}` |
| `sendGroupTyping` | `groupId` | `stop` (default false) | null |
| `createGroup` | `groupName` | `members[]`, `avatar` | `{groupId}` (base64) |
| `listGroups` | — | — | `[{objectPath, groupId, name}]` |
| `getGroupMembers` | `groupId` | — | `[numbers]` |
| `joinGroup` | `inviteURI` | — | null |

#### Contacts

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `getSelfNumber` | — | — | `{number}` |
| `getContactName` | `number` | — | `{name}` |
| `getContactNumber` | `name` | — | `{numbers[]}` |
| `setContactName` | `number`, `name` | — | null |
| `isContactBlocked` | `number` | — | `{blocked}` |
| `setContactBlocked` | `number`, `block` | — | null |
| `deleteContact` | `number` | — | null |
| `deleteRecipient` | `number` | — | null |
| `isRegistered` | — | `number` or `numbers[]` | `{result}` or `{results[]}` |
| `listNumbers` | — | — | `{numbers[]}` |
| `setExpirationTimer` | `number`, `expiration` (seconds) | — | null |

#### Profile

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `updateProfile` | `name` or (`givenName` + `familyName`) | `about`, `aboutEmoji`, `avatar`, `remove` | null |

#### Devices

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `addDevice` | `deviceUri` | — | null |
| `listDevices` | — | — | `[{objectPath, id, name}]` |
| `sendContacts` | — | — | null |
| `sendSyncRequest` | — | — | null |

#### Misc

| Method | Required params | Returns |
|--------|----------------|---------|
| `version` | — | `{version}` |
| `submitRateLimitChallenge` | `challenge`, `captcha` | null |
| `uploadStickerPack` | `stickerPackPath` | `{url}` |

## Client examples

### Python (asyncio)

```python
import asyncio
import json
import websockets

async def run():
    async with websockets.connect("ws://localhost:8765") as ws:
        # Send a message
        await ws.send(json.dumps({
            "id": 1,
            "method": "sendMessage",
            "params": {"message": "Hi!", "recipients": ["+4915100000000"]},
        }))
        print("send result:", await ws.recv())

        # Listen for incoming messages
        async for raw in ws:
            event = json.loads(raw)
            if event.get("signal") == "MessageReceived":
                _, sender, group_id, text, _ = event["args"]
                print(f"{sender}: {text}")

asyncio.run(run())
```

### JavaScript (Node.js / browser)

```js
const ws = new WebSocket("ws://localhost:8765");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.signal === "MessageReceived") {
    const [timestamp, sender, groupId, text] = data.args;
    console.log(`${sender}: ${text}`);
  }
};

// Send a message once connected
ws.onopen = () => {
  ws.send(JSON.stringify({
    id: 1,
    method: "sendMessage",
    params: { message: "Hello!", recipients: ["+4915100000000"] },
  }));
};
```

### Simple echo bot (Python)

```python
import asyncio
import json
import websockets

async def echo_bot():
    async with websockets.connect("ws://localhost:8765") as ws:
        async for raw in ws:
            event = json.loads(raw)
            if event.get("signal") != "MessageReceived":
                continue
            _, sender, group_id, text, _ = event["args"]
            if not text:
                continue
            reply_params = (
                {"message": f"echo: {text}", "groupId": group_id[0]}
                if group_id
                else {"message": f"echo: {text}", "recipients": [sender]}
            )
            method = "sendGroupMessage" if group_id else "sendMessage"
            await ws.send(json.dumps({"id": 0, "method": method, "params": reply_params}))

asyncio.run(echo_bot())
```
