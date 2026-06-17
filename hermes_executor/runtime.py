"""Sandbox runtime — scaffolded implementation backed by a process pool."""

from __future__ import annotations

import asyncio
import logging
import os
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

logger = logging.getLogger("hermes_executor.runtime")

DEFAULT_SANDBOX_BASE_DIR = Path("/tmp/hermes-sandboxes")


def _sandbox_base_dir() -> Path:
    raw = os.getenv("SANDBOX_BASE_DIR")
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            raise RuntimeError(
                f"SANDBOX_BASE_DIR must be an absolute path, got: {raw}"
            )
        return path
    return DEFAULT_SANDBOX_BASE_DIR


def _resolve_sandbox_path(workdir: Path, path: str) -> Path:
    """Resolve a sandbox-relative path and ensure it stays inside the workdir."""
    # Treat leading slashes as relative to the sandbox workdir, matching prior
    # behaviour, while blocking `..` escapes and symlink traversal.
    relative = path.lstrip("/")
    target = (workdir / relative).resolve(strict=False)
    if not target.is_relative_to(workdir):
        raise ValueError("Path escapes sandbox workdir")
    return target


class Sandbox:
    """In-memory representation of a sandbox."""

    def __init__(self, spec: SandboxCreateRequest):
        self.id = str(uuid.uuid4())[:8]
        self.spec = spec
        self.status = "running"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.workdir = _sandbox_base_dir() / self.id
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
        logger.info(
            "Created sandbox %s for agent %s (tier=%s, trace_id=%s)",
            sandbox.id,
            sandbox.spec.agent_name,
            sandbox.spec.tier,
            sandbox.spec.trace_id,
        )
        return sandbox.to_response()

    async def destroy(self, sandbox_id: str, trace_id: str | None = None) -> None:
        sandbox = self.sandboxes.get(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")
        sandbox.status = "destroyed"
        # Best-effort cleanup
        import shutil

        shutil.rmtree(sandbox.workdir, ignore_errors=True)
        logger.info(
            "Destroyed sandbox %s (trace_id=%s)",
            sandbox_id,
            trace_id or sandbox.spec.trace_id,
        )

    async def exec(self, sandbox_id: str, req: ExecRequest) -> ExecResponse:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_exec(sandbox.spec.tier, req.command)
        if not allowed:
            logger.warning(
                "Blocked exec in sandbox %s: %s (trace_id=%s)",
                sandbox_id,
                reason,
                trace_id,
            )
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
            logger.warning(
                "Blocked exec in sandbox %s: tier %s requires human approval (trace_id=%s)",
                sandbox_id,
                sandbox.spec.tier,
                trace_id,
            )
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
            proc = await asyncio.create_subprocess_exec(
                *req.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(sandbox.workdir),
            )
        except FileNotFoundError as exc:
            logger.warning(
                "Command not found in sandbox %s: %s (trace_id=%s)",
                sandbox_id,
                req.command,
                trace_id,
            )
            return ExecResponse(
                stdout="",
                stderr=f"Command not found: {exc}",
                exit_code=127,
                trace_id=trace_id,
                run_id=sandbox.id,
            )
        except PermissionError as exc:
            logger.warning(
                "Permission denied executing command in sandbox %s: %s (trace_id=%s)",
                sandbox_id,
                req.command,
                trace_id,
            )
            return ExecResponse(
                stdout="",
                stderr=f"Permission denied: {exc}",
                exit_code=126,
                trace_id=trace_id,
                run_id=sandbox.id,
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=req.timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error(
                "Command timed out in sandbox %s after %ss (trace_id=%s)",
                sandbox_id,
                req.timeout_seconds,
                trace_id,
            )
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
            return ExecResponse(
                stdout="",
                stderr="Command timed out",
                exit_code=124,
                trace_id=trace_id,
                run_id=sandbox.id,
            )

        logger.info(
            "Executed command in sandbox %s (exit_code=%s, trace_id=%s)",
            sandbox_id,
            proc.returncode,
            trace_id,
        )
        return ExecResponse(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=proc.returncode or 0,
            trace_id=trace_id,
            run_id=sandbox.id,
        )

    async def write_file(self, sandbox_id: str, req: WriteFileRequest) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_write(sandbox.spec.tier)
        if not allowed:
            return {"success": False, "error": reason, "trace_id": trace_id, "run_id": sandbox.id}
        try:
            target = _resolve_sandbox_path(sandbox.workdir, req.path)
        except ValueError as exc:
            logger.warning(
                "Blocked path traversal write in sandbox %s: %s (trace_id=%s)",
                sandbox_id,
                req.path,
                trace_id,
            )
            return {
                "success": False,
                "error": str(exc),
                "trace_id": trace_id,
                "run_id": sandbox.id,
            }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(req.content)
        logger.info(
            "Wrote file %s in sandbox %s (trace_id=%s)",
            target,
            sandbox_id,
            trace_id,
        )
        return {"success": True, "path": str(target), "trace_id": trace_id, "run_id": sandbox.id}

    async def read_file(self, sandbox_id: str, path: str, trace_id: str | None = None) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        resolved_trace_id = trace_id or sandbox.spec.trace_id
        try:
            target = _resolve_sandbox_path(sandbox.workdir, path)
        except ValueError as exc:
            logger.warning(
                "Blocked path traversal read in sandbox %s: %s (trace_id=%s)",
                sandbox_id,
                path,
                resolved_trace_id,
            )
            return {
                "success": False,
                "error": str(exc),
                "trace_id": resolved_trace_id,
                "run_id": sandbox.id,
            }
        if not target.exists():
            return {"success": False, "error": "File not found", "trace_id": resolved_trace_id, "run_id": sandbox.id}
        logger.info(
            "Read file %s in sandbox %s (trace_id=%s)",
            target,
            sandbox_id,
            resolved_trace_id,
        )
        return {"success": True, "path": str(target), "content": target.read_text(), "trace_id": resolved_trace_id, "run_id": sandbox.id}

    async def commit(self, sandbox_id: str, req: CommitRequest) -> dict[str, Any]:
        sandbox = self._get(sandbox_id)
        trace_id = req.trace_id or sandbox.spec.trace_id
        allowed, reason = can_deploy(sandbox.spec.tier)
        if not allowed:
            return {"success": False, "error": reason, "trace_id": trace_id, "run_id": sandbox.id}
        # Scaffold: real implementation would push to git remote with human approval.
        logger.info(
            "Commit/push requested in sandbox %s, gated (trace_id=%s)",
            sandbox_id,
            trace_id,
        )
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
