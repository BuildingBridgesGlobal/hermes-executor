"""FastAPI app for Hermes Executor."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

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

runtime = Runtime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="Hermes Executor", version="0.1.0", lifespan=lifespan)


def _apply_trace_id(req, trace_id: str | None) -> None:
    """Use the incoming trace header when the request body did not supply one."""
    if trace_id and req.trace_id is None:
        req.trace_id = trace_id


@app.post("/sandbox", response_model=SandboxResponse)
async def create_sandbox(
    req: SandboxCreateRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
):
    _apply_trace_id(req, x_huvia_trace_id)
    return await runtime.create(req)


@app.delete("/sandbox/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    try:
        await runtime.destroy(sandbox_id)
        return {"status": "destroyed"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/exec", response_model=ExecResponse)
async def exec_command(
    sandbox_id: str,
    req: ExecRequest,
    x_huvia_trace_id: str | None = Header(None, alias="X-HUVIA-TRACE-ID"),
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
):
    _apply_trace_id(req, x_huvia_trace_id)
    try:
        result = await runtime.commit(sandbox_id, req)
        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
