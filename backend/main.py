"""A-Stock Analyst - 后端主入口"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 确保模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from loguru import logger

# 先初始化缓存和迁移
from data.cache import init_db, _migrate_v1_to_v2
init_db()
_migrate_v1_to_v2()

# === 应用实例 ===
app = FastAPI(
    title="A-Stock Analyst API",
    version="0.17",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# === 路由注册 ===
from routes.kline import router as kline_router
from routes.ai import router as ai_router
from routes.favorites import router as favorites_router
from routes.auth import router as auth_router
from routes.strategy import router as strategy_router
# from routes.chanlun import router as chanlun_router  # 暂时注释，chanlun 模块缺失
from routes.signals import router as signals_router
from routes.backtest import router as backtest_router
from routes.openalice import router as openalice_router
from routes.thread import router as thread_router
from routes.chain import router as chain_router
from routes.rss import router as rss_router

try:
    from routes.kronos import router as kronos_router
except Exception:
    kronos_router = None

app.include_router(kline_router)
app.include_router(ai_router)
app.include_router(favorites_router)
app.include_router(auth_router)
app.include_router(strategy_router)
# app.include_router(chanlun_router)  # 暂时禁用，chanlun 模块缺失
app.include_router(signals_router)
app.include_router(backtest_router)
app.include_router(openalice_router)  # OpenAlice AI 集成
if kronos_router:
    app.include_router(kronos_router)  # Kronos 预测引擎
app.include_router(thread_router)  # 12-Factor Thread 状态管理
app.include_router(chain_router)   # 产业链知识图谱查询
app.include_router(rss_router)     # RSS 新闻聚合


# === 启动事件 ===
@app.on_event("startup")
async def startup_event():
    from data.sequoia_engine import _init_picks_table
    _init_picks_table()
    logger.info("后端启动完成")


# === 前端静态文件（必须在所有 API 路由之后注册） ===
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dir.is_dir():
    from starlette.responses import Response
    from starlette.types import Receive, Scope, Send

    import time as _time
    _BUILD_TS = str(int(_time.time()))

    class _NoCacheStaticFiles(StaticFiles):
        """静态资源 — 版本化文件名（index-xxx.js），永久缓存"""
        async def get_response(self, path: str, scope):
            resp = await super().get_response(path, scope)
            # 静态资源带内容哈希（index-xxx.js），永久缓存
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    app.mount("/assets", _NoCacheStaticFiles(directory=str(_frontend_dir / "assets")), name="frontend_assets")
    # Vite base=/a-stock/，HTML 里 JS/CSS 路径带 /a-stock/ 前缀，额外挂载一份
    app.mount("/a-stock/assets", _NoCacheStaticFiles(directory=str(_frontend_dir / "assets")), name="frontend_assets_prefixed")

    _cache_hdrs_no = {
        "Cache-Control": "no-cache",
    }

    async def _serve_index():
        idx = (_frontend_dir / "index.html").read_text(encoding="utf-8")
        import re as _re
        idx = _re.sub(
            r'(src="[^"]*\.js)"',
            rf'\1?v={_BUILD_TS}"',
            idx
        )
        _index_stat = (_frontend_dir / "index.html").stat()
        _last_mod = _time.strftime("%a, %d %b %Y %H:%M:%S GMT", _time.gmtime(_index_stat.st_mtime))
        _hdrs = dict(_cache_hdrs_no)
        _hdrs["Last-Modified"] = _last_mod
        return HTMLResponse(content=idx, headers=_hdrs)

    @app.api_route("/{path:path}", methods=["GET"])
    async def serve_frontend(path: str):
        if path.startswith("api/") or path == "api":
            return HTMLResponse(status_code=404)
        # 兼容 /a-stock/ 前缀（Vite base=/a-stock/）
        stripped = path
        if stripped.startswith("a-stock/"):
            stripped = stripped[len("a-stock/"):]
        file_path = _frontend_dir / stripped
        if file_path.is_file():
            return FileResponse(str(file_path), headers=_cache_hdrs_no)
        return await _serve_index()

    @app.api_route("/a-stock", methods=["GET"])
    async def serve_a_stock_root():
        return await _serve_index()

    @app.api_route("/a-stock/", methods=["GET"])
    async def serve_a_stock_root_slash():
        return await _serve_index()

    logger.info(f"前端静态文件已挂载: {_frontend_dir}")
else:
    logger.warning("前端静态目录不存在 (frontend/dist)，仅 API 模式运行")


if __name__ == "__main__":
    import uvicorn
    logger.info("启动 A-Stock Analyst 后端...")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
