"""
线程状态管理 API 路由 — 12-Factor Agent F5/F6
"""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from data.thread_manager import (
    start, checkpoint, record_error, finish,
    get_status, list_threads, get_latest_checkpoint,
    count_unresolved_errors, resolve_error, get_recovery_context,
)

router = APIRouter(prefix="/api/v1/thread", tags=["thread"])


class StartRequest(BaseModel):
    thread_id: str
    thread_type: str
    meta: dict = {}


class CheckpointRequest(BaseModel):
    thread_id: str
    step_name: str
    progress: Optional[str] = None
    data: dict = {}


class ErrorRequest(BaseModel):
    thread_id: str
    step: str
    error_type: str = "unknown"
    message: str = ""
    attempt: int = 1


class FinishRequest(BaseModel):
    thread_id: str
    status: str = "done"


@router.post("/start")
async def api_start(req: StartRequest):
    """启动一个新线程"""
    return start(req.thread_id, req.thread_type, req.meta)


@router.post("/checkpoint")
async def api_checkpoint(req: CheckpointRequest):
    """记录检查点"""
    return checkpoint(req.thread_id, req.step_name, req.progress, req.data)


@router.post("/error")
async def api_error(req: ErrorRequest):
    """记录结构化错误"""
    return record_error(req.thread_id, req.step, req.error_type, req.message, req.attempt)


@router.post("/finish")
async def api_finish(req: FinishRequest):
    """标记完成"""
    return finish(req.thread_id, req.status)


@router.get("/status/{thread_id}")
async def api_status(thread_id: str):
    """获取线程状态+恢复上下文"""
    result = get_recovery_context(thread_id)
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return result


@router.get("/list")
async def api_list(limit: int = 20, status: str = None):
    """列出所有线程"""
    return {"threads": list_threads(limit, status)}


@router.get("/checkpoint/{thread_id}")
async def api_latest_checkpoint(thread_id: str):
    """获取最近检查点（用于恢复）"""
    cp = get_latest_checkpoint(thread_id)
    if not cp:
        raise HTTPException(status_code=404, detail="No checkpoint found")
    return cp


@router.get("/errors")
async def api_errors(thread_type: str = None, since: str = None):
    """查询未解决错误"""
    return {"errors": count_unresolved_errors(thread_type, since)}


@router.post("/resolve/{error_id}")
async def api_resolve(error_id: int):
    """标记错误已解决"""
    return resolve_error(error_id)


@router.get("/recovery/{thread_id}")
async def api_recovery(thread_id: str):
    """获取完整恢复上下文（供 cron/Hermes 使用）"""
    result = get_recovery_context(thread_id)
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return result
