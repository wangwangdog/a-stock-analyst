#!/bin/bash
# a-stock 服务自动保活
LOG=/tmp/keepalive.log

# 检查 nginx proxy (9900) — 替代 Python proxy
if ! ss -tlnp 2>/dev/null | grep -q 'nginx.*:9900'; then
  echo "$(date) [KEEPALIVE] nginx proxy down, restarting..." >> $LOG
  /home/dogzi/.local/bin/nginx -c /home/dogzi/.local/share/nginx/nginx.conf 2>>$LOG
  # nginx 重启失败可能是旧 master 还在，先 reload 再启动
  /home/dogzi/.local/bin/nginx -c /home/dogzi/.local/share/nginx/nginx.conf -s reload 2>>$LOG || true
  echo "$(date) [KEEPALIVE] nginx proxy restarted or reloaded" >> $LOG
fi

# 检查 uvicorn (9901)
if ! ss -tlnp 2>/dev/null | grep -q ':9901 '; then
  cd /home/dogzi/.openclaw/workspace/a-stock-analyst/backend && \
    nohup /home/dogzi/.openclaw/workspace/a-stock-analyst/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 9901 >> /tmp/uvicorn.log 2>&1 &
  echo "$(date) [KEEPALIVE] uvicorn restarted" >> $LOG
fi

# 检查 chanlun (9903) — 从 a-stock-analyst/chanlun-pro/ 启动
if ! ss -tlnp 2>/dev/null | grep -q ':9903 '; then
  cd /home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro && \
    nohup .venv/bin/python web/chanlun_chart/app.py nobrowser >> /tmp/chanlun.log 2>&1 &
  echo "$(date) [KEEPALIVE] chanlun-pro restarted from a-stock-analyst" >> $LOG
fi
