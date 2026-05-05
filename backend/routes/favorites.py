"""自选股管理 API"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from data.cache import _get_conn

logger = logging.getLogger('favorites_route')
router = APIRouter(prefix="/api/v1", tags=["自选股"])


# 确保自选股表存在
def _ensure_table():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            symbol TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            added_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


_ensure_table()


class FavoriteAdd(BaseModel):
    symbol: str
    name: str = ""


class FavoriteItem(BaseModel):
    symbol: str
    name: str
    added_at: str


@router.get("/favorites", response_model=List[FavoriteItem])
async def list_favorites():
    """获取所有自选股"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT symbol, name, added_at FROM favorites ORDER BY added_at DESC"
    ).fetchall()
    conn.close()
    return [
        FavoriteItem(symbol=r[0], name=r[1] or "", added_at=r[2])
        for r in rows
    ]


@router.post("/favorites")
async def add_favorite(item: FavoriteAdd):
    """添加自选股"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO favorites (symbol, name, added_at) VALUES (?, ?, datetime('now','localtime'))",
            (item.symbol, item.name),
        )
        conn.commit()
        return {"success": True, "symbol": item.symbol}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/favorites/{symbol}")
async def remove_favorite(symbol: str):
    """删除自选股"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM favorites WHERE symbol = ?", (symbol,))
        conn.commit()
        return {"success": True, "symbol": symbol}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/favorites/{symbol}")
async def check_favorite(symbol: str):
    """检查某股票是否在自选"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM favorites WHERE symbol = ?", (symbol,)
    ).fetchone()
    conn.close()
    return {"is_fav": row is not None}
