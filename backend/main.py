"""A-Stock Analyst - 后端主入口"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 确保模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# 先初始化缓存和迁移
from data.cache import init_db, _migrate_v1_to_v2
init_db()
_migrate_v1_to_v2()

from routes.kline import router as kline_router

app = FastAPI(
    title="A-Stock Analyst",
    description="A股数据分析工具 - 胖磊",
    version="0.1.0",
)

# CORS - 允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(kline_router)


# === 启动时数据检查 ===
@app.on_event("startup")
async def startup_check():
    """启动时检查数据新鲜度，必要时提示更新"""
    try:
        from data.cache import _get_conn
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE source='akshare' AND period='daily'"
        )
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            last_date = row[0]
            days_ago = (datetime.now() - datetime.strptime(last_date, "%Y-%m-%d")).days
            logger.info(f"[启动检查] 最新缓存日线数据: {last_date} ({days_ago}天前)")
            if days_ago > 5:
                logger.warning(f"[启动检查] 数据已 {days_ago} 天未更新，建议运行数据更新脚本")
        else:
            logger.info("[启动检查] 缓存中无历史数据，首次运行建议执行批量下载")
    except Exception as e:
        logger.debug(f"[启动检查] 数据检查跳过: {e}")


@app.get("/")
async def root():
    return {
        "service": "A-Stock Analyst",
        "version": "0.1.0",
        "status": "running",
        "api_docs": "/docs",
    }


@app.get("/api/ping")
async def ping():
    return {"pong": True, "time": __import__("datetime").datetime.now().isoformat()}


@app.get("/api/data/status")
async def data_status():
    """数据状态查询"""
    try:
        from data.cache import _get_conn
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT symbol, source, period, COUNT(*) as count, MAX(trade_date) as latest "
            "FROM kline_cache GROUP BY source, period ORDER BY source, period"
        )
        rows = cursor.fetchall()
        conn.close()

        sources = {}
        for r in rows:
            key = f"{r[1]}_{r[2]}"
            sources[key] = {
                "source": r[1],
                "period": r[2],
                "stocks": r[0],
                "records": r[3],
                "latest": r[4],
            }
        return {"status": "ok", "data": sources}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/data/update")
async def trigger_update():
    """手动触发增量更新（后台异步执行）"""
    script = Path(__file__).resolve().parent / "scripts" / "data_update.py"
    if not script.exists():
        return {"status": "error", "message": "更新脚本不存在"}
    try:
        python = sys.executable
        proc = subprocess.Popen(
            [python, str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return {
            "status": "started",
            "message": "数据更新已启动（后台进程）",
            "pid": proc.pid,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    logger.info("启动 A-Stock Analyst 后端...")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
