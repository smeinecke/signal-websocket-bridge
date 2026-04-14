"""HTTP and WebSocket server with AsyncAPI endpoints."""

import asyncio
import json
import logging
import threading
from typing import Callable

import aiohttp
from aiohttp import web

from swb.config import Config
from swb.dbus_client import is_connected

# Handle missing dbus module (system package)
try:
    from dbus.exceptions import DBusException
except ImportError:

    class DBusException(Exception):  # type: ignore[no-redef]
        pass


class WebSocketServer:
    """HTTP/WebSocket server for signalbot."""

    def __init__(
        self,
        config: Config,
        dispatch_func: Callable,
        asyncapi_json_func: Callable,
        asyncapi_yaml_func: Callable,
        connected_clients: set | None = None,
        clients_lock: threading.Lock | None = None,
    ):
        self.config = config
        self.dispatch = dispatch_func
        self.asyncapi_json = asyncapi_json_func
        self.asyncapi_yaml = asyncapi_yaml_func

        # Allow external state to be injected so the DBus signal handler
        # and the WebSocket server share the same client tracking objects.
        self.connected_clients: set[web.WebSocketResponse] = connected_clients if connected_clients is not None else set()
        self.clients_lock: threading.Lock = clients_lock if clients_lock is not None else threading.Lock()

    async def health_handler(self, request: web.Request) -> web.Response:
        """Liveness/readiness probe. Returns 200 when connected to DBus, 503 when reconnecting."""
        if is_connected():
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "reconnecting"}, status=503)

    async def asyncapi_json_handler(self, request: web.Request) -> web.Response:
        """Serve AsyncAPI spec as JSON."""
        spec = self.asyncapi_json()
        return web.json_response(spec)

    async def asyncapi_yaml_handler(self, request: web.Request) -> web.Response:
        """Serve AsyncAPI spec as YAML."""
        import yaml

        spec = self.asyncapi_yaml()
        yaml_str = yaml.dump(spec, default_flow_style=False, sort_keys=False)
        return web.Response(body=yaml_str, content_type="text/yaml")

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for JSON-RPC with optional token auth."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        peer = request.remote or "unknown"

        # Token authentication
        if self.config.token:
            try:
                auth_msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                if auth_msg.type != aiohttp.WSMsgType.TEXT:
                    await ws.send_str(json.dumps({"error": "unauthorized", "detail": "expected text auth message"}))
                    await ws.close()
                    logging.warning(f"Auth failed from {peer}: non-text message")
                    return ws

                try:
                    auth_data = json.loads(auth_msg.data)
                except json.JSONDecodeError:
                    await ws.send_str(json.dumps({"error": "unauthorized", "detail": "invalid JSON"}))
                    await ws.close()
                    logging.warning(f"Auth failed from {peer}: invalid JSON")
                    return ws

                if auth_data.get("auth") != self.config.token:
                    await ws.send_str(json.dumps({"error": "unauthorized"}))
                    await ws.close()
                    logging.warning(f"Auth failed from {peer}: invalid token")
                    return ws

                await ws.send_str(json.dumps({"auth": "ok"}))

            except asyncio.TimeoutError:
                await ws.send_str(json.dumps({"error": "unauthorized", "detail": "auth timeout"}))
                await ws.close()
                logging.warning(f"Auth failed from {peer}: timeout")
                return ws

        with self.clients_lock:
            self.connected_clients.add(ws)
        logging.info(f"WebSocket client connected from {peer}")

        try:
            while True:
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    raw = msg.data
                    logging.debug(f"WebSocket → DBus: {raw}")
                    try:
                        req = json.loads(raw)
                    except json.JSONDecodeError:
                        await ws.send_str(json.dumps({"error": "invalid JSON"}))
                        continue

                    req_id = req.get("id")
                    method = req.get("method", "")
                    params = req.get("params", {})

                    try:
                        result = self.dispatch(method, params)
                        await ws.send_str(json.dumps({"id": req_id, "result": result}))
                    except DBusException as exc:
                        await ws.send_str(json.dumps({"id": req_id, "error": str(exc)}))
                    except (KeyError, TypeError, ValueError) as exc:
                        await ws.send_str(json.dumps({"id": req_id, "error": f"bad params: {exc}"}))
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error(f"WebSocket error: {ws.exception()}")
                    break

        finally:
            with self.clients_lock:
                self.connected_clients.discard(ws)
            logging.info("WebSocket client disconnected")

        return ws

    def init_app(self) -> web.Application:
        """Initialize aiohttp application with routes."""
        app = web.Application()
        app.router.add_get("/health", self.health_handler)
        app.router.add_get("/asyncapi.json", self.asyncapi_json_handler)
        app.router.add_get("/asyncapi.yaml", self.asyncapi_yaml_handler)
        app.router.add_get("/ws", self.websocket_handler)
        app.router.add_get("/", self.websocket_handler)
        return app

    async def run(self):
        """Run the server until cancelled."""
        app = self.init_app()
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, self.config.host, self.config.port)
        await site.start()

        logging.info(f"Server listening on http://{self.config.host}:{self.config.port}")
        logging.info(f"  WebSocket:    ws://{self.config.host}:{self.config.port}/ws")
        logging.info(f"  AsyncAPI JSON: http://{self.config.host}:{self.config.port}/asyncapi.json")
        logging.info(f"  AsyncAPI YAML: http://{self.config.host}:{self.config.port}/asyncapi.yaml")

        try:
            await asyncio.Future()  # run until cancelled
        finally:
            await runner.cleanup()
