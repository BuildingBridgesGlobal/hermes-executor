"""Sandbox runtime — scaffolded implementation backed by a process pool."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    CommitRequest,
    ExecRequest,
    ExecResponse,
    PermissionTier,
    SandboxCreateRequest,
    SandboxResponse,
    WriteFileRequest,
)
from .policy import can_deploy, can_exec, can_write, requires_human_approval


class Sandbox:
    """In-memory representation of a sandbox."""

    def __init__(self, spec: SandboxCreateRequest):
        self.id = str(uuid.uuid4())[:8]
        self.spec = spec
        self.status = "running"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.workdir = Path(f"/tmp/hermes-sandboxes/{self.id}")
        self.workdir.mkdir(parents=True, exist_ok=True)

    def to_response(self) -> SandboxResponse:
        return SandboxResponse(
            id=self.id,
            agent_name=self.spec.agent_name,
            task_id=self.spec.task_id,
            tier=self.spec.tier,
            status=self.status,
            created_at=self.created_at,
            trace_id=self.spec.trace_id,
        )


class Runtime:
    """Manages sandboxes and enforces permission policies."""

    def __init__(self):
        self.sandboxes: dict[str, Sandbox] = {}

    async def create(self, spec: SandboxCreateRequest) -> SandboxResponse:
        sandbox = Sandbox(spec)
        self.sandboxes[sandbox.id] = sandbox
        return sandbox.to_response()

    async def destroy(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes.get(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")
        sandbox.status = "destroyed"
        # Best-effort cleanup
        import shutil
        shutil.rmtree(sandbox.workdir, ignore_errors=True)

    async def exec(self, sandbox_id: str, req: ExecRequest) -> ExecResponse:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_exec(sandbox.spec.tier, req.command)
        if not allowed:
            return ExecResponse(
                stdout="",
                stderr="",
                exit_code=1,
                blocked=True,
                block_reason=reason,
                trace_id=trace_id,
                run_id=sandbox.id,
            )

        # Human-approval gate for deploy-provision and money-legal tiers
        if requires_human_approval(sandbox.spec.tier):
            return ExecResponse(
                stdout="",
                stderr="",
                exit_code=1,
                blocked=True,
                block_reason=(
                    f"Tier '{sandbox.spec.tier}' requires explicit human approval "
                    "before any command execution"
                ),
                trace_id=trace_id,
                run_id=sandbox.id,
            )

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *req.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(sandbox.workdir),
                ),
                timeout=req.timeout_seconds,
            )
            stdout, stderr = await proc.communicate()
            return ExecResponse(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                trace_id=trace_id,
                run_id=sandbox.id,
            )
        except asyncio.TimeoutError:
            return ExecResponse(
                stdout="",
                stderr="Command timed out",
                exit_code=124,
                trace_id=trace_id,
                run_id=sandbox.id,
            )

    async def write_file(self, sandbox_id: str, req: WriteFileRequest) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_write(sandbox.spec.tier)
        if not allowed:
            return {"success": False, "error": reason, "trace_id": trace_id, "run_id": sandbox.id}
        target = sandbox.workdir / req.path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content)
        return {"success": True, "path": str(target), "trace_id": trace_id, "run_id": sandbox.id}

    async def read_file(self, sandbox_id: str, path: str, trace_id: str | None = None) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        resolved_trace_id = trace_id or sandbox.spec.trace_id
        target = sandbox.workdir / path.lstrip("/")
        if not target.exists():
            return {"success": False, "error": "File not found", "trace_id": resolved_trace_id, "run_id": sandbox.id}
        return {"success": True, "path": str(target), "content": target.read_text(), "trace_id": resolved_trace_id, "run_id": sandbox.id}

    async def commit(self, sandbox_id: str, req: CommitRequest) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_deploy(sandbox.spec.tier)
        if not allowed:
            return {"success": False, "error": reason, "trace_id": trace_id, "run_id": sandbox.id}
        # Scaffold: real implementation would push to git remote with human approval.
        return {
            "success": False,
            "error": (
                "Commit/push is gated. Create an approval record in "
                "huvia-core.rid_submission_approvals (or equivalent) first."
            ),
            "trace_id": trace_id,
            "run_id": sandbox.id,
        }

    def _get(self, sandbox_id: str) -> Sandbox:
        sandbox = self.sandboxes.get(sandbox_id)
        if sandbox is None or sandbox.status != "running":
            raise ValueError(f"Sandbox {sandbox_id} not found or not running")
        return sandbox
