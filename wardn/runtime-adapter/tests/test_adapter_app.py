import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from adapter.app import create_app
from adapter.config import AdapterSettings, parse_runtime_args


def fake_server_path() -> Path:
    return Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def adapter_settings() -> AdapterSettings:
    return AdapterSettings(
        command=sys.executable,
        args=[str(fake_server_path())],
        startup_timeout_seconds=5,
        request_timeout_seconds=5,
    )


def test_parse_runtime_args_requires_string_array() -> None:
    assert parse_runtime_args('["a","b"]') == ["a", "b"]

    try:
        parse_runtime_args('["a",1]')
    except ValueError as exc:
        assert "JSON array of strings" in str(exc)
    else:
        raise AssertionError("expected parse_runtime_args to reject non-string array values")


def test_health_and_ready_endpoints() -> None:
    with TestClient(create_app(adapter_settings())) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["command"] == Path(sys.executable).name


def test_mcp_endpoint_forwards_json_rpc_to_stdio_process() -> None:
    with TestClient(create_app(adapter_settings())) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}},
        )
        call_response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"value": "ok"}},
            },
        )

    assert response.status_code == 200
    assert response.json()["result"]["tools"][0]["name"] == "echo"
    assert call_response.status_code == 200
    payload = json.loads(call_response.json()["result"]["content"][0]["text"])
    assert payload == {
        "arguments": {"value": "ok"},
        "initialized": True,
        "name": "echo",
    }


def test_mcp_notification_returns_accepted() -> None:
    with TestClient(create_app(adapter_settings())) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}},
        )

    assert response.status_code == 202
    assert response.content == b""


def test_shutdown_marks_adapter_not_ready() -> None:
    with TestClient(create_app(adapter_settings())) as client:
        assert client.post("/shutdown").json() == {"status": "stopped"}
        response = client.get("/readyz")

    assert response.status_code == 503
