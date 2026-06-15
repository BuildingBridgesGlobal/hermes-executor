"""Pydantic models for the executor API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PermissionTier(StrEnum):
    READ_ONLY = "read-only"
    WRITE_CODE = "write-code"
    RUN_COMMANDS = "run-commands"
    DEPLOY_PROVISION = "deploy-provision"
    MONEY_LEGAL = "money-legal"


class SandboxCreateRequest(BaseModel):
    agent_name: str = Field(..., description="Agent that owns the sandbox")
    task_id: str = Field(..., description="Task or trace ID for audit linkage")
    tier: PermissionTier = Field(default=PermissionTier.READ_ONLY)
    image: str = Field(default="python:3.11-slim", description="Docker image")
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class SandboxResponse(BaseModel):
    id: str
    agent_name: str
    task_id: str
    tier: PermissionTier
    status: str
    created_at: str


class ExecRequest(BaseModel):
    command: list[str]
    workdir: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    blocked: bool = False
    block_reason: str | None = None


class WriteFileRequest(BaseModel):
    path: str
    content: str


class ReadFileResponse(BaseModel):
    path: str
    content: str


class CommitRequest(BaseModel):
    repo_url: str | None = None
    message: str = "Automated commit by HuVia agent"
    branch: str | None = None


class ActionLog(BaseModel):
    sandbox_id: str
    agent_name: str
    task_id: str
    action: str
    tier: PermissionTier
    payload: dict[str, Any]
    result_summary: str
    timestamp: str
