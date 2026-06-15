"""FastAPI app for Hermes Executor."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

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


@app.post("/sandbox", response_model=SandboxResponse)
async def create_sandbox(req: SandboxCreateRequest):
    return await runtime.create(req)


@app.delete("/sandbox/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    try:
        await runtime.destroy(sandbox_id)
        return {"status": "destroyed"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/exec", response_model=ExecResponse)
async def exec_command(sandbox_id: str, req: ExecRequest):
    try:
        return await runtime.exec(sandbox_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/write")
async def write_file(sandbox_id: str, req: WriteFileRequest):
    try:
        result = await runtime.write_file(sandbox_id, req)
        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sandbox/{sandbox_id}/read")
async def read_file(sandbox_id: str, path: str):
    try:
        result = await runtime.read_file(sandbox_id, path)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error"))
        return ReadFileResponse(path=result["path"], content=result["content"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sandbox/{sandbox_id}/commit")
async def commit(sandbox_id: str, req: CommitRequest):
    try:
        result = await runtime.commit(sandbox_id, req)
        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
