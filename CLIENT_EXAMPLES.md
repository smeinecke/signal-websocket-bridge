# Client Examples

Example code for connecting to the signal-websocket-bridge via WebSocket or HTTP.

## Simple HTTP POST (curl)

For one-off commands without maintaining a WebSocket connection:

```bash
# Send a message
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{"method": "sendMessage", "params": {"message": "Hello!", "recipients": ["+4915100000000"]}}'

# With authentication
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"method": "version"}'

# Multi-account mode
curl -X POST "http://localhost:8765/send?account=+4915100000000" \
  -H "Content-Type: application/json" \
  -d '{"method": "listGroups"}'
```

## Python (asyncio)

Basic connection with authentication and message handling:

```python
import asyncio
import json
import websockets

TOKEN = "your-secret-token"  # omit if no token configured

async def run():
    async with websockets.connect("ws://localhost:8765/ws") as ws:
        # Authenticate (skip if no token)
        await ws.send(json.dumps({"auth": TOKEN}))
        assert json.loads(await ws.recv()) == {"auth": "ok"}

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
                print(f"{event['sender']}: {event['message']}")

asyncio.run(run())
```

## JavaScript (Node.js / browser)

```js
const ws = new WebSocket("ws://localhost:8765/ws");
const TOKEN = "your-secret-token";

ws.onopen = () => {
  // Authenticate
  ws.send(JSON.stringify({ auth: TOKEN }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.auth === "ok") {
    // Auth confirmed — send a message
    ws.send(JSON.stringify({
      id: 1,
      method: "sendMessage",
      params: { message: "Hello!", recipients: ["+4915100000000"] },
    }));
    return;
  }

  if (data.signal === "MessageReceived") {
    console.log(`${data.sender}: ${data.message}`);
  }
  if (data.signal === "Disconnected") {
    console.warn("Bridge lost connection to signal-cli, waiting for Reconnected...");
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
