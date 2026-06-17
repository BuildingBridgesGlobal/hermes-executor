"""FastAPI app for Hermes Executor."""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .models import (
    CommitRequest,
    ExecRequest,
    ExecResponse,
    ReadFileResponse,
    SandboxCreateRequest,
    SandboxResponse,
    WriteFileRequest,
)
from .runtime import Runtime

logger = logging.getLogger("hermes_executor.api")

runtime = Runtime()


def _api_key() -> str | None:
    """Return the configured API key, if any.

    Prefer HERMES_EXECUTOR_API_KEY; fall back to HUVIA_API_KEY for legacy
    deployments that share the same key across services.
    """
    return os.getenv("HERMES_EXECUTOR_API_KEY") or os.getenv("HUVIA_API_KEY")


def verify_api_key(
    authorization: str | None = Header(None),
    x_huvia_api_key: str | None = Header(None, alias="X-HUVIA-API-KEY"),
) -> None:
    """Reject requests without a valid API key when one is configured."""
    expected = _api_key()
    if not expected:
        raise HTTPException(
            status_code=401,
            detail="HUVIA_API_KEY is not configured on the executor",
        )

    candidate = x_huvia_api_key
    if candidate is None and authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:]

    if candidate is None or not secrets.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set HERMES_EXECUTOR_API_KEY.",
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not _api_key():
        raise RuntimeError(
            "HERMES_EXECUTOR_API_KEY (or legacy HUVIA_API_KEY) is required. "
            "Set it before starting Hermes Executor."
        )
    yield


app = FastAPI(title="Hermes Executor", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unhandled errors with the trace id and return a generic 500."""
    trace_id = request.headers.get("X-HUVIA-TRACE-ID")
    logger.exception(
        "Unhandled executor error",
        extra={"trace_id": trace_id, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def _apply_trace_id(req, trace_id: str | None) -> None:
    """Use the incoming trace header when the request body did not supply one."""
    if trace_id and req.trace_id is None:
        req.trace_id = trace_id


@app.post("/sandbox", response_model=SandboxResponse)
async def create_sandbox(
    req: SandboxCreateRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    _apply_trace_id(req, x_huvia_trace_id)
    return await runtime.create(req)


@app.delete("/sandbox/{sandbox_id}")
async def destroy_sandbox(
    sandbox_id: str,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    try:
        await runtime.destroy(sandbox_id, trace_id=x_huvia_trace_id)
        return {"status": "destroyed"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/exec", response_model=ExecResponse)
async def exec_command(
    sandbox_id: str,
    req: ExecRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    _apply_trace_id(req, x_huvia_trace_id)
    try:
        return await runtime.exec(sandbox_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/write")
async def write_file(
    sandbox_id: str,
    req: WriteFileRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    _apply_trace_id(req, x_huvia_trace_id)
    try:
        result = await runtime.write_file(sandbox_id, req)
        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sandbox/{sandbox_id}/read")
async def read_file(
    sandbox_id: str,
    path: str,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    try:
        result = await runtime.read_file(sandbox_id, path, trace_id=x_huvia_trace_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error"))
        return ReadFileResponse(
            path=result["path"],
            content=result["content"],
            trace_id=result.get("trace_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/commit")
async def commit(
    sandbox_id: str,
    req: CommitRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
    _api_key: None = Depends(verify_api_key),
):
    _apply_trace_id(req, x_huvia_trace_id)
    try:
        result = await runtime.commit(sandbox_id, req)
        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
