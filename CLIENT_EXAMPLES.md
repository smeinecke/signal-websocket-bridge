# Client Examples

Example code for connecting to the signal-websocket-bridge via WebSocket or HTTP.

## Simple HTTP POST (curl)

For one-off commands without maintaining a WebSocket connection:

```bash
# Check version / connectivity
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "version"}'

# Send a direct message
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "sendMessage", "params": {"message": "Hello!", "recipients": ["+4915100000000"]}}'

# Send a group message (groupId is base64-encoded)
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "sendGroupMessage", "params": {"message": "Hello group!", "groupId": "<base64-group-id>"}}'

# List all groups
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "listGroups"}'

# Get your own phone number
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "getSelfNumber"}'

# With authentication enabled
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"method": "version"}'

# Multi-account mode (specify which account to use)
curl -X POST "http://localhost:8765/send?account=+4915100000000" \
  -H "Content-Type: application/json" \
  -d '{"method": "listGroups"}'
```

## Python (asyncio)

Basic connection with authentication, message handling, and auto-retry on reconnect:

```python
import asyncio
import json
import websockets

TOKEN = "your-secret-token"  # omit if no token configured

async def call(ws, pending: dict, method: str, params: dict, req_id: int):
    """Send a JSON-RPC call and store it as pending so it can be retried on reconnect."""
    msg = {"id": req_id, "method": method, "params": params}
    pending[req_id] = msg
    await ws.send(json.dumps(msg))

async def run():
    pending = {}  # id -> request, for retry after reconnect

    async with websockets.connect("ws://localhost:8765/ws") as ws:
        # Authenticate (skip if no token)
        await ws.send(json.dumps({"auth": TOKEN}))
        assert json.loads(await ws.recv()) == {"auth": "ok"}

        # Send a message
        await call(ws, pending, "sendMessage", {
            "message": "Hi!", "recipients": ["+4915100000000"],
        }, req_id=1)

        async for raw in ws:
            event = json.loads(raw)

            # Incoming signal
            if "signal" in event:
                if event["signal"] == "MessageReceived":
                    print(f"{event['sender']}: {event['message']}")
                elif event["signal"] == "Reconnected":
                    print("Reconnected — retrying pending calls")
                    for msg in list(pending.values()):
                        await ws.send(json.dumps(msg))
                continue

            # RPC response
            req_id = event.get("id")
            if "error" in event:
                if event.get("reconnecting"):
                    # Transient — keep in pending, will retry after Reconnected
                    print(f"Request {req_id} failed during reconnect, will retry")
                else:
                    # Permanent error — remove from pending
                    pending.pop(req_id, None)
                    print(f"Request {req_id} error: {event['error']}")
            else:
                pending.pop(req_id, None)  # success — no longer needs retry
                print(f"Request {req_id} result: {event['result']}")

asyncio.run(run())
```

## JavaScript (Node.js / browser)

```js
const ws = new WebSocket("ws://localhost:8765/ws");
const TOKEN = "your-secret-token";
const pending = new Map(); // id -> request, for retry after reconnect

function call(method, params, id) {
  const msg = { id, method, params };
  pending.set(id, msg);
  ws.send(JSON.stringify(msg));
}

ws.onopen = () => {
  ws.send(JSON.stringify({ auth: TOKEN }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // Auth handshake
  if (data.auth === "ok") {
    call("sendMessage", { message: "Hello!", recipients: ["+4915100000000"] }, 1);
    return;
  }

  // Incoming signal
  if (data.signal) {
    if (data.signal === "MessageReceived") {
      console.log(`${data.sender}: ${data.message}`);
    } else if (data.signal === "Disconnected") {
      console.warn("Bridge lost connection to signal-cli, waiting for Reconnected...");
    } else if (data.signal === "Reconnected") {
      console.log("Reconnected — retrying pending calls");
      for (const msg of pending.values()) {
        ws.send(JSON.stringify(msg));
      }
    }
    return;
  }

  // RPC response
  if (data.error) {
    if (data.reconnecting) {
      // Transient — keep in pending, will retry after Reconnected
      console.warn(`Request ${data.id} failed during reconnect, will retry`);
    } else {
      // Permanent error
      pending.delete(data.id);
      console.error(`Request ${data.id} error:`, data.error);
    }
  } else {
    pending.delete(data.id); // success
    console.log(`Request ${data.id} result:`, data.result);
  }
};
```

## Simple Echo Bot (Python)

Replies to every direct or group message with an echo:

```python
import asyncio
import json
import websockets

async def echo_bot():
    async with websockets.connect("ws://localhost:8765/ws") as ws:
        async for raw in ws:
            event = json.loads(raw)
            if event.get("signal") != "MessageReceived":
                continue
            sender = event["sender"]
            group_id = event["groupId"]
            text = event["message"]
            if not text:
                continue
            if group_id:
                method = "sendGroupMessage"
                params = {"message": f"echo: {text}", "groupId": group_id}
            else:
                method = "sendMessage"
                params = {"message": f"echo: {text}", "recipients": [sender]}
            await ws.send(json.dumps({"id": 0, "method": method, "params": params}))

asyncio.run(echo_bot())
```

## Python (HTTP requests)

For simple synchronous calls without WebSocket overhead:

```python
import requests

# Simple message send
response = requests.post("http://localhost:8765/send", json={
    "method": "sendMessage",
    "params": {"message": "Hello!", "recipients": ["+4915100000000"]}
})
print(response.json())

# With authentication
response = requests.post(
    "http://localhost:8765/send",
    headers={"Authorization": "Bearer your-secret-token"},
    json={"method": "version"}
)
print(response.json())

# Multi-account mode
response = requests.post(
    "http://localhost:8765/send?account=+4915100000000",
    json={"method": "listGroups"}
)
print(response.json())
```
