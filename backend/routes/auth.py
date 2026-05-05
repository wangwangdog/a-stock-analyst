"""简易登录 + 分析缓存"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from data.cache import _get_conn

logger = logging.getLogger('auth_route')
router = APIRouter(prefix="/api/auth", tags=["登录"])


def _ensure_tables():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            display_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_cache (
            username TEXT,
            symbol TEXT,
            analysis_type TEXT,
            result_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (username, symbol, analysis_type)
        )
    """)
    conn.commit()
    conn.close()

_ensure_tables()


class LoginRequest(BaseModel):
    username: str


@router.post("/login")
async def login(req: LoginRequest):
    """登录 / 自动注册"""
    conn = _get_conn()
    user = conn.execute("SELECT * FROM users WHERE username=?", (req.username,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (username, display_name) VALUES (?, ?)",
                      (req.username, req.username))
        conn.commit()
        logger.info(f"新用户注册: {req.username}")
    conn.close()
    return {"success": True, "username": req.username}


@router.get("/me")
async def get_me(username: str = ""):
    if username:
        return {"logged_in": True, "username": username}
    return {"logged_in": False}


class CacheRequest(BaseModel):
    symbol: str
    analysis_type: str  # "quick" or "deep"
    username: str = ""
    result_json: str = ""


@router.post("/cache/check")
async def check_cache(req: CacheRequest):
    """检查最近2个交易日内是否有缓存的分析结果"""
    if not req.username:
        return {"cached": False}
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT result_json FROM analysis_cache WHERE username=? AND symbol=? AND analysis_type=? AND created_at > ?",
        (req.username, req.symbol, req.analysis_type, cutoff)
    ).fetchone()
    conn.close()
    if row and row[0] and row[0] != "{}":
        try:
            return {"cached": True, "result": json.loads(row[0])}
        except:
            pass
    return {"cached": False}


@router.post("/cache/save")
async def save_cache(req: CacheRequest):
    """保存分析结果到缓存"""
    if not req.username:
        return {"success": False}
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO analysis_cache (username, symbol, analysis_type, result_json, created_at) VALUES (?, ?, ?, ?, datetime('now','localtime'))",
        (req.username, req.symbol, req.analysis_type, req.result_json or "{}")
    )
    conn.commit()
    conn.close()
    return {"success": True}
