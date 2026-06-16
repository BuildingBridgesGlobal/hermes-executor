"""Tests for the Hermes Executor API surface, focused on trace propagation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_executor.api import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_create_sandbox_applies_trace_id_from_header(client: TestClient) -> None:
    response = client.post(
        "/sandbox",
        headers={"X-HUVIA-TRACE-ID": "trace-executor-123"},
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
        headers={"X-HUVIA-TRACE-ID": "trace-fallback-456"},
        json={
            "agent_name": "operator",
            "task_id": "task-2",
            "tier": "run-commands",
        },
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        json={"command": ["echo", "hello"], "timeout_seconds": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-fallback-456"
    assert data["stdout"] == "hello\n"


def test_exec_command_uses_request_trace_id_when_provided(client: TestClient) -> None:
    create_response = client.post(
        "/sandbox",
        headers={"X-HUVIA-TRACE-ID": "trace-sandbox-789"},
        json={
            "agent_name": "operator",
            "task_id": "task-3",
            "tier": "run-commands",
        },
    )
    sandbox_id = create_response.json()["id"]

    response = client.post(
        f"/sandbox/{sandbox_id}/exec",
        headers={"X-HUVIA-TRACE-ID": "trace-exec-override"},
        json={"command": ["echo", "hello"], "timeout_seconds": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "trace-exec-override"
