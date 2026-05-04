#!/usr/bin/env bash
# A-Stock Analyst 启动脚本
# 后端端口: 8765, 前端端口: 3000

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🦞 A-Stock Analyst 启动中..."
echo ""

# 启动后端
echo "[1/2] 启动后端 API..."
cd "$DIR/backend"
PYTHONPATH="." PATH="$PATH:$HOME/Library/Python/3.9/bin" \
  python3 -m uvicorn main:app --host 0.0.0.0 --port 8765 --log-level info &
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
