#!/bin/bash
# a-stock 服务自动保活
LOG=/tmp/keepalive.log
# 检查 proxy
if ! ss -tlnp 2>/dev/null | grep -q ':9900 '; then
  cd /home/dogzi/.openclaw/workspace/skillgate/deploy && python3 proxy.py &
  echo "$(date) proxy restarted" >> $LOG
fi
# 检查 uvicorn
if ! ss -tlnp 2>/dev/null | grep -q ':9901 '; then
  cd /home/dogzi/.openclaw/workspace/a-stock-analyst/backend && ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 9901 &
  echo "$(date) uvicorn restarted" >> $LOG
fi
