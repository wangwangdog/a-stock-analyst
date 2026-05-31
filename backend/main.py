"""A-Stock Analyst - 后端主入口"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 确保模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from loguru import logger

# 先初始化缓存和迁移
from data.cache import init_db, _migrate_v1_to_v2
init_db()
_migrate_v1_to_v2()

from routes.kline import router as kline_router
from routes.ai import router as ai_router
from routes.favorites import router as favorites_router
from routes.auth import router as auth_router
from routes.strategy import router as strategy_router
# from routes.chanlun import router as chanlun_router  # 暂时注释，chanlun 模块缺失
from routes.signals import router as signals_router
from routes.backtest import router as backtest_router
from routes.openalice import router as openalice_router
from routes.kronos import router as kronos_router

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
app.include_router(ai_router)
app.include_router(favorites_router)
app.include_router(auth_router)
app.include_router(strategy_router)
# app.include_router(chanlun_router)  # 暂时禁用，chanlun 模块缺失
app.include_router(signals_router)
app.include_router(backtest_router)
app.include_router(openalice_router)  # OpenAlice AI 集成
app.include_router(kronos_router)  # Kronos 预测引擎

# === 启动时数据检查 ===
@app.on_event("startup")
async def startup_check():
    """启动时检查数据新鲜度，必要时提示更新"""
    try:
        from data.cache import _get_conn
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE source='baostock' AND period='daily'"
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


@app.get("/api/root")
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


# === 前端静态文件（必须在所有 API 路由之后注册） ===
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dir.is_dir():
    from starlette.responses import Response
    from starlette.types import Receive, Scope, Send

    class _NoCacheStaticFiles(StaticFiles):
        """静态资源 + no-cache 头"""
        async def get_response(self, path: str, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

    app.mount("/assets", _NoCacheStaticFiles(directory=str(_frontend_dir / "assets")), name="frontend_assets")

    _cache_hdrs = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.api_route("/{path:path}", methods=["GET"])
    async def serve_frontend(path: str):
        if path.startswith("api/") or path == "api":
            return HTMLResponse(status_code=404)
        file_path = _frontend_dir / path
        if file_path.is_file():
            return FileResponse(str(file_path), headers=_cache_hdrs)
        return FileResponse(str(_frontend_dir / "index.html"), headers=_cache_hdrs)

    logger.info(f"前端静态文件已挂载: {_frontend_dir}")
else:
    logger.warning("前端静态目录不存在 (frontend/dist)，仅 API 模式运行")


if __name__ == "__main__":
    import uvicorn
    logger.info("启动 A-Stock Analyst 后端...")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
