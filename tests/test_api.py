"""Tests for the Hermes Executor API surface, focused on trace propagation."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("HUVIA_API_KEY", "test-api-key")

from hermes_executor.api import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HUVIA_API_KEY", "test-api-key")
    monkeypatch.setenv("SANDBOX_BASE_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _auth_header(key: str = "test-api-key") -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_missing_api_key_returns_401(client: TestClient) -> None:
    response = client.post(
        "/sandbox",
        json={"agent_name": "rook", "task_id": "task-1", "tier": "run-commands"},
    )
    assert response.status_code == 401


def test_invalid_api_key_returns_401(client: TestClient) -> None:
    response = client.post(
        "/sandbox",
        headers=_auth_header("wrong-key"),
        json={"agent_name": "rook", "task_id": "task-1", "tier": "run-commands"},
    )
    assert response.status_code == 401


def test_x_huvia_api_key_header_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/sandbox",
        headers={"X-HUVIA-API-KEY": "test-api-key"},
        json={"agent_name": "rook", "task_id": "task-1", "tier": "run-commands"},
    )
    assert response.status_code == 200


def test_create_sandbox_applies_trace_id_from_header(client: TestClient) -> None:
    response = client.post(
        "/sandbox",
        headers={**_auth_header(), "X-HUVIA-TRACE-ID": "trace-executor-123"},
        json={
            "agent_name": "rook",
            "task_id": "task-1",
            "tier": "run-commands",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-executor-123"
    assert data["agent_name"] == "rook"
    assert data["tier"] == "run-commands"


def test_exec_command_falls_back_to_sandbox_trace_id(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers={**_auth_header(), "X-HUVIA-TRACE-ID": "trace-fallback-456"},
        json={
            "agent_name": "operator",
            "task_id": "task-2",
            "tier": "run-commands",
        },
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers=_auth_header(),
        json={"command": ["echo", "hello"], "timeout_seconds": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-fallback-456"
    assert data["stdout"] == "hello\n"


def test_exec_command_uses_request_trace_id_when_provided(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers={**_auth_header(), "X-HUVIA-TRACE-ID": "trace-sandbox-789"},
        json={
            "agent_name": "operator",
            "task_id": "task-3",
            "tier": "run-commands",
        },
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers={**_auth_header(), "X-HUVIA-TRACE-ID": "trace-exec-override"},
        json={"command": ["echo", "hello"], "timeout_seconds": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-exec-override"


def test_destructive_command_is_blocked(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-4", "tier": "run-commands"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers=_auth_header(),
        json={"command": ["rm", "-rf", "/"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert "Destructive pattern" in data["block_reason"]


def test_command_not_found_returns_127(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-5", "tier": "run-commands"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers=_auth_header(),
        json={"command": ["definitely-not-a-real-binary-xyz"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 127
    assert "not found" in data["stderr"].lower()


def test_command_timeout_kills_process(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-6", "tier": "run-commands"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers=_auth_header(),
        json={"command": ["sleep", "5"], "timeout_seconds": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 124
    assert "timed out" in data["stderr"].lower()


def test_write_and_read_file_round_trip(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-7", "tier": "write-code"},
    )
    sandbox_id = create_response.json()["id"]

    write_response = client.post(
        f"/sandbox/{sandbox_id}/write",
        headers=_auth_header(),
        json={"path": "src/main.py", "content": "print('hello')"},
    )
    assert write_response.status_code == 200
    assert write_response.json()["success"] is True

    read_response = client.get(
        f"/sandbox/{sandbox_id}/read",
        headers=_auth_header(),
        params={"path": "src/main.py"},
    )
    assert read_response.status_code == 200
    data = read_response.json()
    assert data["content"] == "print('hello')"


def test_write_blocked_for_read_only_tier(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-8", "tier": "read-only"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/write",
        headers=_auth_header(),
        json={"path": "file.txt", "content": "x"},
    )
    assert response.status_code == 403


def test_path_traversal_write_is_blocked(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-9", "tier": "write-code"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/write",
        headers=_auth_header(),
        json={"path": "../escape.txt", "content": "bad"},
    )
    assert response.status_code == 403
    assert "escapes" in response.json()["detail"].lower()


def test_path_traversal_read_is_blocked(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-10", "tier": "run-commands"},
    )
    sandbox_id = create_response.json()["id"]

    response = client.get(
        f"/sandbox/{sandbox_id}/read",
        headers=_auth_header(),
        params={"path": "../escape.txt"},
    )
    assert response.status_code == 404
    assert "escapes" in response.json()["detail"].lower()


def test_commit_is_gated(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={
            "agent_name": "operator",
            "task_id": "task-11",
            "tier": "deploy-provision",
        },
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/commit",
        headers=_auth_header(),
        json={"message": "test commit"},
    )
    assert response.status_code == 403
    assert "gated" in response.json()["detail"].lower()


def test_destroy_sandbox_requires_auth(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers=_auth_header(),
        json={"agent_name": "operator", "task_id": "task-12", "tier": "run-commands"},
    )
    sandbox_id = create_response.json()["id"]

    no_auth = client.delete(f"/sandbox/{sandbox_id}")
    assert no_auth.status_code == 401

    ok = client.delete(f"/sandbox/{sandbox_id}", headers=_auth_header())
    assert ok.status_code == 200
    assert ok.json()["status"] == "destroyed"
