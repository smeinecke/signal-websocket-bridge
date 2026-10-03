"""Integration test for signal-cli communication via Docker container.

This test verifies that:
1. The Docker container starts successfully with signal-cli daemon
2. DBus communication with signal-cli works (version check)
3. The WebSocket bridge health endpoint responds
4. Basic WebSocket connection can be established
5. WebSocket authentication works (success and failure cases)
6. Version can be retrieved via authenticated WebSocket
7. DBus signals are serialized and broadcast to connected clients
8. Events buffered while no client is connected are replayed on connect
9. The bridge detects signal-cli restarts and reconnects autonomously
"""

import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import pytest

# Constants
CONTAINER_NAME = "swb-integration-test"
WEBSOCKET_PORT = 9876
HEALTH_URL = f"http://localhost:{WEBSOCKET_PORT}/health"
WS_URL = f"ws://localhost:{WEBSOCKET_PORT}/ws"
TEST_TOKEN = "test-secret-token-12345"
BUFFER_CONTAINER_NAME = "swb-integration-buffered"
BUFFER_PORT = 9877
BUFFER_WS_URL = f"ws://localhost:{BUFFER_PORT}/ws"


@asynccontextmanager
async def ws_connect(url: str, timeout: float = 5):
    """Open an aiohttp WebSocket client connection."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.ws_connect(url) as ws:
            yield ws


async def ws_recv_json(ws, timeout: float = 5) -> dict:
    """Receive one text frame and decode it as JSON."""
    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
    return json.loads(msg.data)


async def ws_wait_for_signal(ws, signal_name: str, timeout: float) -> dict:
    """Read incoming messages until one carries {"signal": signal_name}."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"did not receive signal {signal_name!r} within {timeout}s")
        msg = await ws_recv_json(ws, timeout=remaining)
        if msg.get("signal") == signal_name:
            return msg


def _emit_signal(container: str, member: str, *args: str) -> None:
    """Emit a signal on the container's session bus via dbus-send."""
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "dbus-send",
            "--bus=unix:path=/tmp/dbus-session.socket",
            "--type=signal",
            "/org/asamk/Signal",
            f"org.asamk.Signal.{member}",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def _run_container(name: str, port: int, extra_env: list[str]) -> None:
    """Start a swb:integration container and wait until it is healthy."""
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{port}:8765",
            "-e",
            "SIGNAL_WS_HOST=0.0.0.0",
            "-e",
            "SIGNAL_WS_PORT=8765",
            "-e",
            "SIGNAL_DBUS_BUS=session",
            "-e",
            "SIGNAL_LOG_LEVEL=DEBUG",
            "-e",
            f"SIGNAL_WS_TOKEN={TEST_TOKEN}",
            *extra_env,
            "swb:integration",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    max_wait = 90  # seconds
    start_time = time.time()

    while time.time() - start_time < max_wait:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "healthy" in result.stdout:
            break
        time.sleep(2)
    else:
        logs = subprocess.run(
            ["docker", "logs", name],
            capture_output=True,
            text=True,
        )
        pytest.fail(f"Container {name} failed to become healthy within timeout\n{logs.stdout}\n{logs.stderr}")

    # Give a bit more time for everything to stabilize
    time.sleep(3)


@pytest.fixture(scope="module")
def docker_container():
    """Build the image and start the main container for integration testing."""
    project_root = Path(__file__).parent.parent.parent

    # Build the Docker image
    print("\nBuilding Docker image...")
    subprocess.run(
        ["docker", "build", "-t", "swb:integration", "."],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    print("Docker image built successfully")

    print("Starting Docker container...")
    _run_container(CONTAINER_NAME, WEBSOCKET_PORT, [])

    yield CONTAINER_NAME

    # Cleanup
    print("\nCleaning up container...")
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="module")
def docker_container_buffered(docker_container):
    """Second container with SIGNAL_BUFFER_SIZE enabled for replay tests."""
    _run_container(BUFFER_CONTAINER_NAME, BUFFER_PORT, ["-e", "SIGNAL_BUFFER_SIZE=50"])

    yield BUFFER_CONTAINER_NAME

    subprocess.run(
        ["docker", "rm", "-f", BUFFER_CONTAINER_NAME],
        capture_output=True,
        check=False,
    )


class TestSignalCliIntegration:
    """Integration tests for signal-cli communication."""

    def test_container_running(self, docker_container):
        """Verify the container is running."""
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", docker_container],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "running" in result.stdout

    def test_signal_cli_daemon_running(self, docker_container):
        """Verify signal-cli daemon process is running inside container."""
        result = subprocess.run(
            ["docker", "exec", docker_container, "pgrep", "-f", "daemon --dbus"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "signal-cli daemon is not running"
        assert result.stdout.strip(), "No signal-cli daemon process found"

    def test_dbus_daemon_running(self, docker_container):
        """Verify DBus daemon is running inside container."""
        result = subprocess.run(
            ["docker", "exec", docker_container, "pgrep", "dbus-daemon"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "DBus daemon is not running"

    def test_signal_cli_version_via_dbus(self, docker_container):
        """Test signal-cli version can be retrieved via DBus."""
        # Use dbus-send to call the version method
        result = subprocess.run(
            [
                "docker",
                "exec",
                docker_container,
                "dbus-send",
                "--bus=unix:path=/tmp/dbus-session.socket",
                "--print-reply",
                "--dest=org.asamk.Signal",
                "/org/asamk/Signal",
                "org.asamk.Signal.version",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"DBus call failed: {result.stderr}"
        # The response should contain the version string
        assert "string" in result.stdout or "0." in result.stdout, f"Unexpected DBus response: {result.stdout}"

    def test_health_endpoint(self, docker_container):
        """Test the HTTP health endpoint returns OK."""
        import urllib.request

        max_retries = 10
        for i in range(max_retries):
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
                    assert response.status == 200
                    data = json.loads(response.read().decode())
                    assert data.get("status") == "ok"
                    return
            except Exception as e:
                if i == max_retries - 1:
                    pytest.fail(f"Health endpoint failed after {max_retries} retries: {e}")
                time.sleep(1)

    def test_asyncapi_endpoint(self, docker_container):
        """Test the AsyncAPI spec endpoint returns a populated spec from DBus introspection."""
        import urllib.request

        url = f"http://localhost:{WEBSOCKET_PORT}/asyncapi.json"
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.status == 200
            data = json.loads(response.read().decode())

        # Top-level structure
        assert data.get("asyncapi") == "2.6.0"
        assert "info" in data
        assert "channels" in data

        # Introspection actually populated the spec - non-empty means DBus worked
        schemas = data.get("components", {}).get("schemas", {})
        messages = data.get("components", {}).get("messages", {})
        assert schemas, f"AsyncAPI spec has no schemas - DBus introspection likely failed. Spec components: {list(data.get('components', {}).keys())}"
        assert messages, "AsyncAPI spec has no messages - DBus introspection likely failed."

        # signal-cli always exposes a 'version' method - reliable canary
        assert "version_request" in schemas, f"Expected 'version_request' schema from signal-cli DBus introspection. Got schemas: {list(schemas.keys())}"
        assert "version" in messages, f"Expected 'version' message. Got messages: {list(messages.keys())}"

    @pytest.mark.asyncio
    async def test_websocket_connection(self, docker_container):
        """Test WebSocket connection can be established and authenticated."""
        max_retries = 10
        last_error = None

        for i in range(max_retries):
            try:
                async with ws_connect(WS_URL) as ws:
                    # Authenticate first
                    await ws.send_str(json.dumps({"auth": TEST_TOKEN}))

                    # Wait for auth response
                    auth_response = await ws_recv_json(ws)

                    # Verify auth success
                    assert auth_response.get("auth") == "ok", f"Auth failed: {auth_response}"
                    return
            except Exception as e:
                last_error = e
                if i == max_retries - 1:
                    break
                await asyncio.sleep(1)

        pytest.fail(f"WebSocket connection failed after {max_retries} retries: {last_error}")

    @pytest.mark.asyncio
    async def test_websocket_auth_and_version(self, docker_container):
        """Test WebSocket authentication and version call."""
        max_retries = 10

        for i in range(max_retries):
            try:
                async with ws_connect(WS_URL) as ws:
                    # Step 1: Send authentication
                    await ws.send_str(json.dumps({"auth": TEST_TOKEN}))

                    # Step 2: Wait for auth response
                    auth_response = await ws_recv_json(ws)

                    # Verify auth success
                    assert auth_response.get("auth") == "ok", f"Auth failed: {auth_response}"

                    # Step 3: Send version request
                    await ws.send_str(
                        json.dumps({
                            "id": 1,
                            "method": "version",
                            "params": {},
                        })
                    )

                    # Step 4: Wait for version response
                    response = await ws_recv_json(ws)

                    # Verify response structure
                    assert "id" in response
                    assert response["id"] == 1
                    assert "result" in response
                    # Result should contain version string
                    result = response["result"]
                    assert isinstance(result, str) or isinstance(result, dict)
                    if isinstance(result, str):
                        assert result.startswith("0.")  # signal-cli version format
                    return
            except Exception as e:
                if i == max_retries - 1:
                    # Get logs for debugging
                    logs = subprocess.run(
                        ["docker", "logs", docker_container],
                        capture_output=True,
                        text=True,
                    )
                    pytest.fail(f"WebSocket auth/version call failed: {e}\nContainer logs:\n{logs.stdout}\n{logs.stderr}")
                await asyncio.sleep(1)

    @pytest.mark.asyncio
    async def test_websocket_auth_failure(self, docker_container):
        """Test WebSocket connection with invalid token is rejected."""
        async with ws_connect(WS_URL) as ws:
            # Send invalid auth
            await ws.send_str(json.dumps({"auth": "invalid-token"}))

            # Wait for error response
            response = await ws_recv_json(ws)

            # Verify auth failure
            assert "error" in response
            assert response.get("error") == "unauthorized"

    @pytest.mark.asyncio
    async def test_websocket_signal_method_dispatch(self, docker_container):
        """Test that a real org.asamk.Signal method dispatches without UnknownObject.

        Calls listGroups which requires the per-account DBus object to exist.
        Without a registered account the result may be empty or an account-level
        error - but it must never be an UnknownObject DBus error, which would
        indicate the bridge's _signal_interface points to a non-existent path.
        """
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            auth = await ws_recv_json(ws)
            assert auth.get("auth") == "ok", f"Auth failed: {auth}"

            await ws.send_str(json.dumps({"id": 2, "method": "listGroups", "params": {}}))
            response = await ws_recv_json(ws, timeout=10)

        assert response.get("id") == 2
        error = response.get("error", "")
        assert "UnknownObject" not in error, f"listGroups returned UnknownObject - bridge _signal_interface points to a non-existent DBus path: {error}"
        assert "result" in response or "error" in response

    @pytest.mark.asyncio
    async def test_websocket_non_object_json(self, docker_container):
        """A JSON array message is rejected without killing the connection."""
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"

            await ws.send_str("[1, 2, 3]")
            response = await ws_recv_json(ws)
            assert response.get("error") == "expected JSON object"

            # Connection stays usable after the malformed message
            await ws.send_str(json.dumps({"id": 4, "method": "version", "params": {}}))
            response = await ws_recv_json(ws)
            assert response.get("id") == 4
            assert "result" in response

    @pytest.mark.asyncio
    async def test_websocket_unknown_method(self, docker_container):
        """Unknown method names return a descriptive error."""
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"

            await ws.send_str(json.dumps({"id": 5, "method": "noSuchMethod", "params": {}}))
            response = await ws_recv_json(ws)
            assert response.get("id") == 5
            assert "unknown method" in response.get("error", "")

    def test_send_endpoint_version(self, docker_container):
        """POST /send performs a synchronous dispatch with Bearer auth."""
        req = urllib.request.Request(
            f"http://localhost:{WEBSOCKET_PORT}/send",
            data=json.dumps({"id": 3, "method": "version", "params": {}}).encode(),
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
        assert data.get("id") == 3
        assert "result" in data

    def test_send_endpoint_unauthorized(self, docker_container):
        """POST /send rejects invalid tokens with 401."""
        req = urllib.request.Request(
            f"http://localhost:{WEBSOCKET_PORT}/send",
            data=b"{}",
            headers={"Authorization": "Bearer wrong-token"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 401

    @pytest.mark.asyncio
    async def test_dbus_signal_broadcast_to_client(self, docker_container):
        """A DBus signal on the bus is serialized and pushed to WS clients.

        Baseline for the dbus library migration: the signal path
        (receiver -> serialize_signal -> broadcast) must be preserved,
        including ay -> base64 conversion for groupId.
        """
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"

            _emit_signal(
                docker_container,
                "MessageReceived",
                "int64:1234567890",
                "string:+491234567890",
                "array:byte:1,2,3",
                "string:e2e test message",
                "array:string:/tmp/a.txt",
            )
            msg = await ws_wait_for_signal(ws, "MessageReceived", timeout=10)

        assert msg["timestamp"] == 1234567890
        assert msg["sender"] == "+491234567890"
        assert msg["groupId"] == "AQID"  # base64 of b"\\x01\\x02\\x03"
        assert msg["message"] == "e2e test message"
        assert msg["attachments"] == ["/tmp/a.txt"]
        assert "event_id" in msg

    @pytest.mark.asyncio
    async def test_dbus_unknown_signal_fallback(self, docker_container):
        """Unknown signals are broadcast in the generic {signal, args} format."""
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"

            _emit_signal(docker_container, "SomethingCustom", "string:hello", "int32:42")
            msg = await ws_wait_for_signal(ws, "SomethingCustom", timeout=10)

        assert msg["args"] == ["hello", 42]

    @pytest.mark.asyncio
    async def test_event_buffer_replay(self, docker_container_buffered):
        """Events received while no client is connected are replayed on connect.

        Baseline for the dbus library migration: the signal -> buffer ->
        replay path must keep working end to end. Uses a separate container
        with SIGNAL_BUFFER_SIZE=50.
        """
        _emit_signal(
            docker_container_buffered,
            "MessageReceived",
            "int64:987654321",
            "string:+49987654321",
            "array:byte:",
            "string:buffered event",
            "array:string:",
        )

        # The signal was emitted with no client connected; the new
        # connection must receive it from the replay buffer.
        async with ws_connect(BUFFER_WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"
            msg = await ws_wait_for_signal(ws, "MessageReceived", timeout=10)

        assert msg["timestamp"] == 987654321
        assert msg["sender"] == "+49987654321"
        assert msg["groupId"] is None  # empty ay -> None
        assert msg["message"] == "buffered event"
        assert msg["attachments"] == []

    def test_bridge_process_running(self, docker_container):
        """Verify the WebSocket bridge process is running."""
        result = subprocess.run(
            ["docker", "exec", docker_container, "pgrep", "-f", "python -m swb"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "WebSocket bridge is not running"

    @pytest.mark.asyncio
    async def test_reconnect_after_signal_cli_restart(self, docker_container):
        """Killing signal-cli triggers Disconnected/Reconnected broadcasts.

        Baseline for the dbus library migration: supervisord autorestarts
        signal-cli; the bridge must detect the outage, notify clients, and
        recover on its own. Runs last since it disturbs the shared container.
        """
        async with ws_connect(WS_URL) as ws:
            await ws.send_str(json.dumps({"auth": TEST_TOKEN}))
            assert (await ws_recv_json(ws)).get("auth") == "ok"

            subprocess.run(
                ["docker", "exec", docker_container, "pkill", "-f", "signal-cli"],
                capture_output=True,
                check=True,
                timeout=10,
            )

            # The bridge learns of the outage lazily: either via a failed call
            # (ServiceUnknown is instant once the bus name vanishes) or via the
            # 30s watchdog probe. Probe with version calls until detection is
            # confirmed by an error response or the Disconnected broadcast.
            saw_disconnected = False
            for _ in range(5):
                await ws.send_str(json.dumps({"id": 6, "method": "version", "params": {}}))
                msg = await ws_recv_json(ws, timeout=20)
                if msg.get("signal") == "Disconnected":
                    saw_disconnected = True
                    break
                if "error" in msg:
                    break  # reconnect path triggered; broadcast arrives next
                await asyncio.sleep(2)
            else:
                pytest.fail("signal-cli outage was never detected")

            if not saw_disconnected:
                disconnected = await ws_wait_for_signal(ws, "Disconnected", timeout=30)
                assert disconnected["signal"] == "Disconnected"

            # Health endpoint reports the outage while disconnected
            try:
                urllib.request.urlopen(HEALTH_URL, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 503

            # supervisord restarts signal-cli; the reconnect loop reattaches
            reconnected = await ws_wait_for_signal(ws, "Reconnected", timeout=90)
            assert reconnected["signal"] == "Reconnected"

            # Dispatch works against the new connection. A stale error
            # response for the probe call (id=6) may still be queued.
            await ws.send_str(json.dumps({"id": 7, "method": "version", "params": {}}))
            for _ in range(5):
                response = await ws_recv_json(ws, timeout=15)
                if response.get("id") == 7:
                    break
            else:
                pytest.fail("no response for id=7 after reconnect")
            assert "result" in response


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
