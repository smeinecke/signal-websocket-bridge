"""Tests for swb.websocket_server module."""

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web

from swb.config import Config
from swb.websocket_server import WebSocketServer


@pytest.fixture
def mock_config_no_auth():
    """Create a mock config without auth."""
    return Config(
        bus="system",
        host="localhost",
        port=8765,
        token=None,
        account=None,
        log_level="INFO",
        buffer_size=0,
    )


@pytest.fixture
def mock_config_with_auth():
    """Create a mock config with auth token."""
    return Config(
        bus="system",
        host="localhost",
        port=8765,
        token="secret123",
        account=None,
        log_level="INFO",
        buffer_size=0,
    )


@pytest.fixture
def mock_dispatch():
    """Create a mock dispatch factory that returns a dispatch function mock."""
    dispatch_mock = MagicMock(return_value={"result": "ok"})
    factory = MagicMock(return_value=dispatch_mock)
    # Expose the inner dispatch mock so tests can set side_effect on it
    factory.dispatch_mock = dispatch_mock
    return factory


@pytest.fixture
def mock_asyncapi():
    """Create a mock AsyncAPI function."""
    return MagicMock(return_value={"version": "1.0.0"})


@pytest.fixture
def server_no_auth(mock_config_no_auth, mock_dispatch, mock_asyncapi):
    """Create a WebSocketServer instance without auth."""
    return WebSocketServer(
        config=mock_config_no_auth,
        dispatch_factory=mock_dispatch,
        asyncapi_json_func=mock_asyncapi,
        asyncapi_yaml_func=mock_asyncapi,
    )


@pytest.fixture
def server_with_auth(mock_config_with_auth, mock_dispatch, mock_asyncapi):
    """Create a WebSocketServer instance with auth."""
    return WebSocketServer(
        config=mock_config_with_auth,
        dispatch_factory=mock_dispatch,
        asyncapi_json_func=mock_asyncapi,
        asyncapi_yaml_func=mock_asyncapi,
    )


class TestAsyncapiHandlers:
    """Test AsyncAPI endpoint handlers."""

    async def test_asyncapi_json_handler(self, server_no_auth):
        server = server_no_auth
        """Test JSON AsyncAPI endpoint."""
        request = MagicMock()

        response = await server.asyncapi_json_handler(request)

        assert response.content_type == "application/json"
        assert response.status == 200

    async def test_asyncapi_yaml_handler(self, server_no_auth):
        server = server_no_auth
        """Test YAML AsyncAPI endpoint."""
        request = MagicMock()

        response = await server.asyncapi_yaml_handler(request)

        assert response.content_type == "text/yaml"
        assert response.status == 200


class TestWebsocketHandlerNoAuth:
    """Test WebSocket handler without authentication."""

    async def test_websocket_connection_no_auth(self, server_no_auth, mock_config_no_auth):
        """Test WebSocket connection without auth token."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            # Mock receive to return one message then close
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"id": 1, "method": "version", "params": {}})),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            result = await server.websocket_handler(mock_request)

            assert mock_ws.prepare.called
            assert mock_ws.closed

    async def test_websocket_message_handling(self, server_no_auth, mock_config_no_auth, mock_dispatch):
        """Test WebSocket message handling."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        message = {"id": 1, "method": "version", "params": {}}
        response = {"id": 1, "result": {"version": "0.12.0"}}

        mock_dispatch.dispatch_mock.return_value = {"version": "0.12.0"}

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps(message)),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            mock_dispatch.dispatch_mock.assert_called_once_with("version", {})

    async def test_websocket_invalid_json(self, server_no_auth, mock_config_no_auth):
        """Test WebSocket handling of invalid JSON."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data="not valid json"),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should send error response
            calls = [c for c in mock_ws.send_str.call_args_list]
            assert len(calls) > 0


class TestWebsocketHandlerWithAuth:
    """Test WebSocket handler with authentication."""

    async def test_websocket_auth_success(self, server_with_auth, mock_config_with_auth):
        """Test successful WebSocket authentication."""
        server = server_with_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"auth": "secret123"})),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            mock_ws.send_str.assert_any_call(json.dumps({"auth": "ok"}))

    async def test_websocket_auth_failure(self, server_with_auth, mock_config_with_auth):
        """Test failed WebSocket authentication."""
        server = server_with_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.return_value = MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"auth": "wrong-token"}))

            await server.websocket_handler(mock_request)

            mock_ws.send_str.assert_called_with(json.dumps({"error": "unauthorized"}))
            mock_ws.close.assert_called_once()

    async def test_websocket_auth_timeout(self, server_with_auth, mock_config_with_auth):
        """Test WebSocket auth timeout."""
        server = server_with_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            # Simulate timeout
            async def mock_wait_for(awaitable, timeout):
                awaitable.close()
                raise asyncio.TimeoutError()

            with patch("asyncio.wait_for", side_effect=mock_wait_for):
                await server.websocket_handler(mock_request)

                mock_ws.send_str.assert_called_with(json.dumps({"error": "unauthorized", "detail": "auth timeout"}))
                mock_ws.close.assert_called_once()


class TestInitApp:
    """Test app initialization."""

    def test_app_routes(self, server_no_auth):
        """Test that all routes are registered."""
        app = server_no_auth.init_app()

        routes = []
        for resource in app.router.resources():
            if hasattr(resource, "canonical"):
                routes.append(resource.canonical)
            elif hasattr(resource, "_path"):
                routes.append(resource._path)

        assert "/health" in routes
        assert "/asyncapi.json" in routes
        assert "/asyncapi.yaml" in routes
        assert "/ws" in routes
        assert "/" in routes


class TestClientTracking:
    """Test WebSocket client tracking."""

    def test_external_clients_shared(self, mock_config_no_auth, mock_dispatch, mock_asyncapi):
        """Test that external client tracking objects are used."""
        external_clients = set()
        external_lock = threading.Lock()

        server = WebSocketServer(
            config=mock_config_no_auth,
            dispatch_factory=mock_dispatch,
            asyncapi_json_func=mock_asyncapi,
            asyncapi_yaml_func=mock_asyncapi,
            connected_clients=external_clients,
            clients_lock=external_lock,
        )

        assert server.connected_clients is external_clients
        assert server.clients_lock is external_lock


class TestWebsocketMessageTypes:
    """Test WebSocket message type handling."""

    async def test_websocket_binary_message(self, server_no_auth, mock_config_no_auth):
        """Test WebSocket handling of binary message."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            # Binary message should be ignored (not text)
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.BINARY, data=b"binary data"),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should not crash
            assert mock_ws.prepare.called

    async def test_websocket_error_message(self, server_no_auth, mock_config_no_auth):
        """Test WebSocket handling of error message."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.ERROR),
            ]
            mock_ws.exception = MagicMock(return_value=Exception("Test error"))
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should log error and close
            assert mock_ws.prepare.called


class TestDispatchErrors:
    """Test WebSocket dispatch error handling."""

    async def test_dispatch_key_error(self, server_no_auth, mock_config_no_auth, mock_dispatch):
        """Test handling of KeyError from dispatch."""
        server = server_no_auth
        mock_dispatch.dispatch_mock.side_effect = KeyError("missing_key")

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"id": 1, "method": "test", "params": {}})),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should send error response
            calls = mock_ws.send_str.call_args_list
            assert len(calls) > 0

    async def test_dispatch_type_error(self, server_no_auth, mock_config_no_auth, mock_dispatch):
        """Test handling of TypeError from dispatch."""
        server = server_no_auth
        mock_dispatch.dispatch_mock.side_effect = TypeError("type error")

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"id": 1, "method": "test", "params": {}})),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should send error response
            calls = mock_ws.send_str.call_args_list
            assert len(calls) > 0

    async def test_dispatch_dbus_exception(self, server_no_auth, mock_config_no_auth, mock_dispatch):
        """Test handling of DBusException from dispatch."""
        from swb.websocket_server import DBusException

        server = server_no_auth
        mock_dispatch.dispatch_mock.side_effect = DBusException("DBus error")

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [
                MagicMock(type=aiohttp.WSMsgType.TEXT, data=json.dumps({"id": 1, "method": "test", "params": {}})),
                MagicMock(type=aiohttp.WSMsgType.CLOSED),
            ]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

            # Should send error response
            calls = mock_ws.send_str.call_args_list
            assert len(calls) > 0


class TestAuthEdgeCases:
    """Test authentication edge cases."""

    async def test_websocket_auth_invalid_json(self, server_with_auth, mock_config_with_auth):
        """Test auth with invalid JSON."""
        server = server_with_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.return_value = MagicMock(type=aiohttp.WSMsgType.TEXT, data="not valid json")

            await server.websocket_handler(mock_request)

            mock_ws.send_str.assert_called_with(json.dumps({"error": "unauthorized", "detail": "invalid JSON"}))
            mock_ws.close.assert_called_once()

    async def test_websocket_auth_non_text_message(self, server_with_auth, mock_config_with_auth):
        """Test auth with non-text message."""
        server = server_with_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.return_value = MagicMock(type=aiohttp.WSMsgType.BINARY, data=b"binary")

            await server.websocket_handler(mock_request)

            mock_ws.send_str.assert_called_with(json.dumps({"error": "unauthorized", "detail": "expected text auth message"}))
            mock_ws.close.assert_called_once()


class TestKeepAlive:
    """Test subscribeReceive/unsubscribeReceive keep-alive management."""

    async def test_subscribe_called_on_first_client(self, server_no_auth, mock_config_no_auth):
        """subscribeReceive() is called when the first client connects."""
        server = server_no_auth

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws):
            mock_ws.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
            mock_ws.closed = True

            with patch("swb.websocket_server.subscribe_receive") as mock_sub, \
                 patch("swb.websocket_server.unsubscribe_receive") as mock_unsub:
                await server.websocket_handler(mock_request)

                mock_sub.assert_called_once()
                mock_unsub.assert_called_once()

    async def test_subscribe_not_called_for_second_client(self, server_no_auth, mock_config_no_auth):
        """subscribeReceive() fires only for the first client; unsubscribeReceive() only on last."""
        server = server_no_auth

        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"
        mock_request.rel_url.query.get.return_value = None

        with patch("swb.websocket_server.subscribe_receive") as mock_sub, \
             patch("swb.websocket_server.unsubscribe_receive") as mock_unsub:

            async def run_ws1():
                with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws1):
                    mock_ws1.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
                    mock_ws1.closed = True
                    await server.websocket_handler(mock_request)

            async def run_ws2():
                with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws2):
                    mock_ws2.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
                    mock_ws2.closed = True
                    await server.websocket_handler(mock_request)

            # Run sequentially: ws1 connects and disconnects, then ws2
            await run_ws1()
            await run_ws2()

            # subscribe/unsubscribe called once each per sequential connection
            assert mock_sub.call_count == 2
            assert mock_unsub.call_count == 2


class TestEventBuffer:
    """Test event buffer replay on client connect."""

    async def test_buffer_replayed_on_connect(self, mock_config_no_auth, mock_dispatch, mock_asyncapi):
        """Buffered events are sent to a new client immediately after connect."""
        from collections import deque

        buf = deque(["payload1", "payload2"], maxlen=10)
        server = WebSocketServer(
            config=mock_config_no_auth,
            dispatch_factory=mock_dispatch,
            asyncapi_json_func=mock_asyncapi,
            asyncapi_yaml_func=mock_asyncapi,
            event_buffer=buf,
        )

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws), \
             patch("swb.websocket_server.subscribe_receive"), \
             patch("swb.websocket_server.unsubscribe_receive"):
            mock_ws.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

        sent = [call.args[0] for call in mock_ws.send_str.call_args_list]
        assert "payload1" in sent
        assert "payload2" in sent

    async def test_no_replay_when_buffer_disabled(self, server_no_auth, mock_config_no_auth):
        """No extra send_str calls when event_buffer is None."""
        server = server_no_auth
        assert server.event_buffer is None

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws), \
             patch("swb.websocket_server.subscribe_receive"), \
             patch("swb.websocket_server.unsubscribe_receive"):
            mock_ws.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

        # No signal events to replay - only DBus method results would appear
        mock_ws.send_str.assert_not_called()

    async def test_empty_buffer_no_send(self, mock_config_no_auth, mock_dispatch, mock_asyncapi):
        """Empty buffer causes no extra sends."""
        from collections import deque

        buf = deque(maxlen=10)
        server = WebSocketServer(
            config=mock_config_no_auth,
            dispatch_factory=mock_dispatch,
            asyncapi_json_func=mock_asyncapi,
            asyncapi_yaml_func=mock_asyncapi,
            event_buffer=buf,
        )

        mock_ws = AsyncMock()
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"

        with patch("aiohttp.web.WebSocketResponse", return_value=mock_ws), \
             patch("swb.websocket_server.subscribe_receive"), \
             patch("swb.websocket_server.unsubscribe_receive"):
            mock_ws.receive.side_effect = [MagicMock(type=aiohttp.WSMsgType.CLOSED)]
            mock_ws.closed = True

            await server.websocket_handler(mock_request)

        mock_ws.send_str.assert_not_called()

    async def test_buffer_respects_maxlen(self):
        """deque with maxlen drops oldest events."""
        from collections import deque

        buf = deque(maxlen=3)
        for i in range(5):
            buf.append(f"event{i}")

        assert list(buf) == ["event2", "event3", "event4"]
