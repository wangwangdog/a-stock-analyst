"""自选股管理 API - 关联用户名"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List

from data.cache import _get_conn

logger = logging.getLogger('favorites_route')
router = APIRouter(prefix="/api/v1", tags=["自选股"])


def _ensure_table():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            username TEXT,
            symbol TEXT,
            name TEXT DEFAULT '',
            added_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (username, symbol)
        )
    """)
    conn.commit()
    conn.close()

_ensure_table()


class FavoriteAdd(BaseModel):
    username: str
    symbol: str
    name: str = ""


class FavoriteItem(BaseModel):
    symbol: str
    name: str
    added_at: str


@router.get("/favorites", response_model=List[FavoriteItem])
async def list_favorites(username: str = Query("")):
    """获取指定用户的自选股"""
    if not username:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT symbol, name, added_at FROM favorites WHERE username=? ORDER BY added_at DESC",
        (username,)
    ).fetchall()
    conn.close()
    return [FavoriteItem(symbol=r[0], name=r[1] or "", added_at=r[2]) for r in rows]


@router.post("/favorites")
async def add_favorite(item: FavoriteAdd):
    """添加自选股"""
    if not item.username:
        raise HTTPException(status_code=400, detail="需要用户名")
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO favorites (username, symbol, name, added_at) VALUES (?, ?, ?, datetime('now','localtime'))",
            (item.username, item.symbol, item.name),
        )
        conn.commit()
        return {"success": True, "symbol": item.symbol}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/favorites/{symbol}")
async def remove_favorite(symbol: str, username: str = Query("")):
    """删除指定用户的自选股"""
    if not username:
        raise HTTPException(status_code=400, detail="需要用户名")
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM favorites WHERE symbol=? AND username=?", (symbol, username))
        conn.commit()
        return {"success": True, "symbol": symbol}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/favorites/{symbol}")
async def check_favorite(symbol: str, username: str = Query("")):
    """检查某股票是否在指定用户的自选中"""
    if not username:
        return {"is_fav": False}
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM favorites WHERE symbol=? AND username=?", (symbol, username)
    ).fetchone()
    conn.close()
    return {"is_fav": row is not None}
