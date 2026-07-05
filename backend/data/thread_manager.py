"""
线程状态管理器 — 12-Factor Agent F5/F6 实现

持久化长任务的状态、检查点、错误，支持中断恢复。

用法：
    from data.thread_manager import ThreadManager
    tm = ThreadManager()
    tm.start("daily_sync", {"date": "2026-06-27", "total_stocks": 5087})
    tm.checkpoint("daily_sync", {"step": "tencent_fq", "progress": "30%", "count": 1500})
    tm.record_error("daily_sync", {"step": "baostock_login", "error": "timeout", "attempt": 2})
    tm.resume("daily_sync")  # → 返回最后一个成功的检查点
"""

import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, date
from typing import Optional

# ── 数据库路径 ──
DB_PATH = Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite")

# ── 表名 ──
THREAD_TABLE = "agent_threads"
CHECKPOINT_TABLE = "agent_checkpoints"
ERROR_TABLE = "agent_errors"

# ── 线程锁 ──
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """获取线程安全的连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def _init_tables():
    """初始化所有表（幂等）"""
    conn = _get_conn()
    try:
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS {THREAD_TABLE} (
                thread_id TEXT PRIMARY KEY,
                thread_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                finished_at TEXT,
                meta_json TEXT DEFAULT '{{}}',
                error_count INTEGER DEFAULT 0,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS {CHECKPOINT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                progress TEXT,
                data_json TEXT DEFAULT '{{}}',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (thread_id) REFERENCES {THREAD_TABLE}(thread_id)
            );

            CREATE TABLE IF NOT EXISTS {ERROR_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                step TEXT NOT NULL,
                error_type TEXT DEFAULT 'unknown',
                message TEXT,
                attempt INTEGER DEFAULT 1,
                resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (thread_id) REFERENCES {THREAD_TABLE}(thread_id)
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoint_thread ON {CHECKPOINT_TABLE}(thread_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_error_thread ON {ERROR_TABLE}(thread_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_thread_status ON {THREAD_TABLE}(status);
        """)
        conn.commit()
    finally:
        conn.close()
        _local.conn = None


# ═══════════════════════════════════════════════
#  Thread API
# ═══════════════════════════════════════════════


def start(thread_id: str, thread_type: str, meta: dict = None) -> dict:
    """启动一个新线程"""
    _init_tables()
    conn = _get_conn()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            f"""INSERT OR REPLACE INTO {THREAD_TABLE}
               (thread_id, thread_type, status, started_at, updated_at, meta_json)
               VALUES (?, ?, 'running', ?, ?, ?)""",
            (thread_id, thread_type, now, now, meta_json),
        )
        conn.commit()
        return {"thread_id": thread_id, "status": "running", "started_at": now}
    finally:
        conn.close()
        _local.conn = None


def checkpoint(thread_id: str, step_name: str, progress: str = None, data: dict = None) -> dict:
    """记录一个检查点"""
    _init_tables()
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_json = json.dumps(data or {}, ensure_ascii=False)
    try:
        conn.execute(
            f"UPDATE {THREAD_TABLE} SET status='running', updated_at=? WHERE thread_id=?",
            (now, thread_id),
        )
        conn.execute(
            f"""INSERT INTO {CHECKPOINT_TABLE}
               (thread_id, step_name, progress, data_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (thread_id, step_name, progress, data_json, now),
        )
        conn.commit()
        return {"thread_id": thread_id, "step": step_name, "progress": progress}
    finally:
        conn.close()
        _local.conn = None


def record_error(thread_id: str, step: str, error_type: str = "unknown",
                 message: str = "", attempt: int = 1) -> dict:
    """记录一个结构化错误"""
    _init_tables()
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            f"""INSERT INTO {ERROR_TABLE}
               (thread_id, step, error_type, message, attempt, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (thread_id, step, error_type, message, attempt, now),
        )
        conn.execute(
            f"UPDATE {THREAD_TABLE} SET error_count=error_count+1, last_error=?, updated_at=? WHERE thread_id=?",
            (message[:500], now, thread_id),
        )
        conn.commit()
        return {"thread_id": thread_id, "step": step, "error_type": error_type}
    finally:
        conn.close()
        _local.conn = None


def finish(thread_id: str, status: str = "done") -> dict:
    """标记线程完成（done/failed）"""
    _init_tables()
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            f"UPDATE {THREAD_TABLE} SET status=?, finished_at=?, updated_at=? WHERE thread_id=?",
            (status, now, now, thread_id),
        )
        conn.commit()
        return {"thread_id": thread_id, "status": status, "finished_at": now}
    finally:
        conn.close()
        _local.conn = None


def get_status(thread_id: str) -> Optional[dict]:
    """获取线程状态"""
    _init_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM {THREAD_TABLE} WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["meta"] = json.loads(result.pop("meta_json", "{}"))
        # 取最近3个检查点
        cps = conn.execute(
            f"SELECT * FROM {CHECKPOINT_TABLE} WHERE thread_id=? ORDER BY created_at DESC LIMIT 3",
            (thread_id,),
        ).fetchall()
        result["recent_checkpoints"] = [dict(cp) for cp in cps]
        # 取最近3个错误
        errs = conn.execute(
            f"SELECT * FROM {ERROR_TABLE} WHERE thread_id=? ORDER BY created_at DESC LIMIT 3",
            (thread_id,),
        ).fetchall()
        result["recent_errors"] = [dict(e) for e in errs]
        return result
    finally:
        conn.close()
        _local.conn = None


def list_threads(limit: int = 20, status: str = None) -> list[dict]:
    """列出最近线程"""
    _init_tables()
    conn = _get_conn()
    try:
        sql = f"SELECT * FROM {THREAD_TABLE}"
        params = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
        _local.conn = None


def get_latest_checkpoint(thread_id: str) -> Optional[dict]:
    """获取最近一个成功的检查点（用于恢复）"""
    _init_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM {CHECKPOINT_TABLE} WHERE thread_id=? ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row:
            result = dict(row)
            result["data"] = json.loads(result.pop("data_json", "{}"))
            return result
        return None
    finally:
        conn.close()
        _local.conn = None


def count_unresolved_errors(thread_type: str = None, since: str = None) -> list[dict]:
    """统计未解决的错误（用于 cron 检查）"""
    _init_tables()
    conn = _get_conn()
    try:
        sql = f"""SELECT e.*, t.thread_type, t.status
                  FROM {ERROR_TABLE} e
                  JOIN {THREAD_TABLE} t ON e.thread_id = t.thread_id
                  WHERE e.resolved = 0"""
        params = []
        if thread_type:
            sql += " AND t.thread_type=?"
            params.append(thread_type)
        if since:
            sql += " AND e.created_at>=?"
            params.append(since)
        sql += " ORDER BY e.created_at DESC LIMIT 50"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
        _local.conn = None


def resolve_error(error_id: int) -> dict:
    """标记一个错误已解决"""
    _init_tables()
    conn = _get_conn()
    try:
        conn.execute(
            f"UPDATE {ERROR_TABLE} SET resolved=1 WHERE id=?", (error_id,)
        )
        conn.commit()
        return {"error_id": error_id, "resolved": True}
    finally:
        conn.close()
        _local.conn = None


def cleanup_old_threads(days: int = 30):
    """清理旧线程记录"""
    _init_tables()
    conn = _get_conn()
    try:
        cutoff = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), days)
        # 找到旧线程的ID以级联删除
        old = conn.execute(
            f"SELECT thread_id FROM {THREAD_TABLE} WHERE started_at < date('now', '-? days')",
            (days,),
        ).fetchall()
        old_ids = tuple(r[0] for r in old)
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM {CHECKPOINT_TABLE} WHERE thread_id IN ({placeholders})", old_ids)
            conn.execute(f"DELETE FROM {ERROR_TABLE} WHERE thread_id IN ({placeholders})", old_ids)
            conn.execute(f"DELETE FROM {THREAD_TABLE} WHERE thread_id IN ({placeholders})", old_ids)
            conn.commit()
        return {"cleaned": len(old_ids)}
    finally:
        conn.close()
        _local.conn = None


def get_recovery_context(thread_id: str) -> dict:
    """获取线程恢复上下文（F9 压缩错误 + F13 预取上下文）"""
    status = get_status(thread_id)
    if not status:
        return {"found": False}

    cp = get_latest_checkpoint(thread_id)
    errors = status.get("recent_errors", [])

    # 压缩错误
    error_summary = []
    for e in errors:
        error_summary.append({
            "step": e["step"],
            "type": e["error_type"],
            "message": e["message"],
            "attempt": e["attempt"],
        })

    return {
        "found": True,
        "thread_id": thread_id,
        "status": status["status"],
        "type": status["thread_type"],
        "last_checkpoint": cp,
        "error_summary": error_summary,
        "resume_from": cp.get("step_name") if cp else None,
        "resume_data": cp.get("data") if cp else None,
    }


# ── 模块级别初始化 ──
_init_tables()
