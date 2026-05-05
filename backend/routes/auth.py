"""简易登录 + 分析缓存"""
import os
import json
import hashlib
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Cookie, Response
from pydantic import BaseModel
from typing import Optional

from data.cache import _get_conn

logger = logging.getLogger('auth_route')
router = APIRouter(prefix="/api/auth", tags=["登录"])


# 确保表存在
def _ensure_tables():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            display_name TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
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
async def login(req: LoginRequest, response: Response):
    """登录 / 自动注册"""
    conn = _get_conn()
    user = conn.execute("SELECT * FROM users WHERE username=?", (req.username,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (username, display_name) VALUES (?, ?)",
                      (req.username, req.username))
        conn.commit()
        logger.info(f"新用户注册: {req.username}")
    
    session = hashlib.md5(f"{req.username}_{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                  (session, req.username))
    conn.commit()
    conn.close()
    
    response.set_cookie(key="session", value=session, max_age=86400*30, httponly=True)
    response.set_cookie(key="un", value=req.username.encode('utf-8').hex(), max_age=86400*30)
    return {"success": True, "username": req.username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session")
    response.delete_cookie("username")
    return {"success": True}


@router.get("/me")
async def get_me(un: Optional[str] = Cookie(None)):
    if un:
        try:
            username = bytes.fromhex(un).decode('utf-8')
            return {"logged_in": True, "username": username}
        except:
            pass
    return {"logged_in": False}


# ── 分析缓存 ──
class CacheCheckRequest(BaseModel):
    symbol: str
    analysis_type: str  # "quick" or "deep"
    result_json: str = ""


def _get_username(un: str = None) -> Optional[str]:
    if un:
        try:
            return bytes.fromhex(un).decode('utf-8')
        except:
            pass
    return None


@router.post("/cache/check")
async def check_cache(req: CacheCheckRequest, un: Optional[str] = Cookie(None)):
    """检查最近2个交易日内是否有缓存的分析结果"""
    username = _get_username(un)
    if not username:
        return {"cached": False}
    conn = _get_conn()
    # 用72小时近似2个交易日(含周末48h不够)
    cutoff = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT result_json FROM analysis_cache WHERE username=? AND symbol=? AND analysis_type=? AND created_at > ?",
        (username, req.symbol, req.analysis_type, cutoff)
    ).fetchone()
    conn.close()
    if row and row[0] and row[0] != "{}":
        try:
            return {"cached": True, "result": json.loads(row[0])}
        except:
            pass
    return {"cached": False}


@router.post("/cache/save")
async def save_cache(req: CacheCheckRequest, un: Optional[str] = Cookie(None)):
    """保存分析结果到缓存"""
    username = _get_username(un)
    if not username:
        return {"success": False}
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO analysis_cache (username, symbol, analysis_type, result_json, created_at) VALUES (?, ?, ?, ?, datetime('now','localtime'))",
        (username, req.symbol, req.analysis_type, req.result_json or "{}")
    )
    conn.commit()
    conn.close()
    return {"success": True}



