#!/usr/bin/env bash
# A-Stock Analyst 启动脚本
# 后端端口: 8765, 前端端口: 3000

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🦞 A-Stock Analyst 启动中..."
echo ""

# ===== 清理旧进程 =====
echo "🧹 清理旧进程..."
lsof -ti :8765 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti :3000 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# 检查 venv
VENV_PYTHON="$DIR/backend/.venv/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "📦 未检测到 venv，创建 Python 3.12 虚拟环境..."
    cd "$DIR/backend"
    /opt/homebrew/bin/python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt 2>/dev/null || echo "⚠️ 部分依赖需手动安装"
    pip install fastapi uvicorn akshare baostock loguru langgraph langchain-core langchain-openai openai chromadb dashscope 2>&1 | tail -3
else
    echo "✅ 使用 venv Python: $VENV_PYTHON"
fi

# 加载 .env 文件 (API Keys)
if [ -f "$DIR/.env" ]; then
    echo "📄 加载 .env 文件"
    export $(grep -v '^#' "$DIR/.env" | xargs)
fi

# 启动后端
echo "[1/2] 启动后端 API..."
cd "$DIR/backend"
PYTHONPATH="." "$VENV_PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8765 --log-level info &
BACKEND_PID=$!
sleep 2

# 启动前端
echo "[2/2] 启动前端服务..."
cd "$DIR/frontend"
npx vite --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!

echo ""
echo "✅ 启动完成!"
echo "   前端: http://localhost:3000"
echo "   后端: http://localhost:8765"
echo "   API文档: http://localhost:8765/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待任意进程退出
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
