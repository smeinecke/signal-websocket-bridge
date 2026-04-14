"""Integration test for signal-cli communication via Docker container.

This test verifies that:
1. The Docker container starts successfully with signal-cli daemon
2. DBus communication with signal-cli works (version check)
3. The WebSocket bridge health endpoint responds
4. Basic WebSocket connection can be established
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest
from websockets.client import connect
from websockets.legacy.client import WebSocketClientProtocol

# Constants
CONTAINER_NAME = "swb-integration-test"
WEBSOCKET_PORT = 9876
HEALTH_URL = f"http://localhost:{WEBSOCKET_PORT}/health"
WS_URL = f"ws://localhost:{WEBSOCKET_PORT}/ws"


@pytest.fixture(scope="module")
def docker_container():
    """Build and start the Docker container for integration testing."""
    project_root = Path(__file__).parent.parent.parent

    # Clean up any existing container
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        check=False,
    )

    # Build the Docker image
    print("\nBuilding Docker image...")
    result = subprocess.run(
        ["docker", "build", "-t", "swb:integration", "."],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    print("Docker image built successfully")

    # Start the container
    print("Starting Docker container...")
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{WEBSOCKET_PORT}:8765",
            "-e",
            "SIGNAL_WS_HOST=0.0.0.0",
            "-e",
            "SIGNAL_WS_PORT=8765",
            "-e",
            "SIGNAL_DBUS_BUS=session",
            "-e",
            "SIGNAL_LOG_LEVEL=DEBUG",
            "swb:integration",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    # Wait for container to be healthy
    print("Waiting for container to be ready...")
    max_wait = 90  # seconds
    start_time = time.time()

    while time.time() - start_time < max_wait:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "healthy" in result.stdout:
            print("Container is healthy")
            break
        time.sleep(2)
    else:
        # Get logs for debugging
        logs = subprocess.run(
            ["docker", "logs", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        print(f"Container logs:\n{logs.stdout}\n{logs.stderr}")
        pytest.fail("Container failed to become healthy within timeout")

    # Give a bit more time for everything to stabilize
    time.sleep(3)

    yield CONTAINER_NAME

    # Cleanup
    print("\nCleaning up container...")
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
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

        # Introspection actually populated the spec — non-empty means DBus worked
        schemas = data.get("components", {}).get("schemas", {})
        messages = data.get("components", {}).get("messages", {})
        assert schemas, (
            "AsyncAPI spec has no schemas — DBus introspection likely failed. "
            f"Spec components: {list(data.get('components', {}).keys())}"
        )
        assert messages, (
            "AsyncAPI spec has no messages — DBus introspection likely failed."
        )

        # signal-cli always exposes a 'version' method — reliable canary
        assert "version_request" in schemas, (
            f"Expected 'version_request' schema from signal-cli DBus introspection. "
            f"Got schemas: {list(schemas.keys())}"
        )
        assert "version" in messages, (
            f"Expected 'version' message. Got messages: {list(messages.keys())}"
        )

    @pytest.mark.asyncio
    async def test_websocket_connection(self, docker_container):
        """Test WebSocket connection can be established."""
        max_retries = 10
        last_error = None

        for i in range(max_retries):
            try:
                async with connect(WS_URL, open_timeout=5) as ws:
                    # Connection established successfully
                    assert isinstance(ws, WebSocketClientProtocol)
                    return
            except Exception as e:
                last_error = e
                if i == max_retries - 1:
                    break
                await asyncio.sleep(1)

        pytest.fail(f"WebSocket connection failed after {max_retries} retries: {last_error}")

    @pytest.mark.asyncio
    async def test_websocket_version_call(self, docker_container):
        """Test calling version method via WebSocket JSON-RPC."""
        max_retries = 10

        for i in range(max_retries):
            try:
                async with connect(WS_URL, open_timeout=5) as ws:
                    # Send version request
                    request = {
                        "id": 1,
                        "method": "version",
                        "params": {},
                    }
                    await ws.send(json.dumps(request))

                    # Wait for response with timeout
                    response_raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    response = json.loads(response_raw)

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
                    pytest.fail(f"WebSocket version call failed: {e}\nContainer logs:\n{logs.stdout}\n{logs.stderr}")
                await asyncio.sleep(1)

    def test_bridge_process_running(self, docker_container):
        """Verify the WebSocket bridge process is running."""
        result = subprocess.run(
            ["docker", "exec", docker_container, "pgrep", "-f", "python -m swb"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "WebSocket bridge is not running"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
