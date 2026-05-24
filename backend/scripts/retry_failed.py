#!/usr/bin/env python3
"""
失败定时任务重试脚本（方案A）
交易日 17:00 运行，检查 health_check 结果，若有失败项则重试对应流水线。
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent
VENV = PROJECT / ".venv" / "bin" / "python3"
ALT_VENV = Path.home() / ".openclaw" / "workspace" / "cl-vendors" / "chanlun-pro" / ".venv" / "bin" / "python3"

PYTHON = str(VENV if VENV.exists() else ALT_VENV)
LOG = Path(f"/tmp/retry_failed_{datetime.now().strftime('%Y%m%d')}.log")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def exec_cmd(cmd, timeout=3600):
    log(f"🔄 执行: {cmd[:120]}")
    try:
        r = subprocess.run(cmd, shell=True, timeout=timeout,
                          capture_output=True, text=True, cwd=str(PROJECT))
        for line in r.stdout.splitlines()[-10:]:
            log(f"  {line}")
        if r.returncode != 0:
            for line in r.stderr.splitlines()[-5:]:
                log(f"  ⚠️  {line}")
            log(f"  ❌ 退出码 {r.returncode}")
            return False
        log(f"  ✅ 完成")
        return True
    except subprocess.TimeoutExpired:
        log(f"  ⏰ 超时")
        return False
    except Exception as e:
        log(f"  💥 异常: {e}")
        return False

def run_health():
    log("--- health_check ---")
    r = subprocess.run(
        [PYTHON, str(BACKEND / "scripts" / "health_check.py"), "--json"],
        capture_output=True, text=True, timeout=120, cwd=str(PROJECT),
    )
    if r.returncode == 0 or r.returncode == 1:
        # exit 0 = all pass, exit 1 = some failed (still valid JSON)
        pass
    else:
        log(f"health_check 异常 (exit {r.returncode}): {r.stderr[:200]}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        log(f"JSON 解析失败: {e}")
        log(f"输出: {r.stdout[:200]}")
        return None

def get_failed(checks):
    return {k: v for k, v in checks.items() if not v.get("passed", False)}

def main():
    today = datetime.now().strftime("%Y-%m-%d %a")
    log(f"{'='*50}")
    log(f"📋 失败任务重试 - {today}")
    log(f"{'='*50}")

    # 1. 检查当前状态
    result = run_health()
    if result is None:
        log("❌ health_check 失败，跳过")
        return False

    checks = result.get("checks", {})
    failed = get_failed(checks)
    log(f"健康检查: {result['passed']}/{result['total']} 通过")

    if result.get("all_passed"):
        log("✅ 全部通过，无需重试")
        return True

    log(f"❌ {len(failed)} 项失败:")
    for name, chk in failed.items():
        log(f"   - {name}: {chk.get('detail','')[:100]}")

    # 2. 重试逻辑
    retried = False

    # 2a. stock_daily → 增量日线
    if any(k.startswith("stock_daily") for k in failed):
        log("\n--- 重试 stock_daily ---")
        retried = True
        exec_cmd(f"bash {PROJECT}/daily_update.sh", timeout=7200)

    # 2b. kline_cache → data_update.py
    if any(k.startswith("kline_cache") for k in failed):
        log("\n--- 重试 kline_cache ---")
        retried = True
        exec_cmd(f"{PYTHON} {BACKEND}/scripts/data_update.py", timeout=7200)

    # 2c. strategy_picks → strategy_sync.py (仅 19:00 后)
    now_hour = datetime.now().hour
    if any(k.startswith("strategy_picks") for k in failed):
        if now_hour >= 19:
            log("\n--- 重试 strategy_sync ---")
            retried = True
            exec_cmd(f"{PYTHON} {BACKEND}/scripts/strategy_sync.py", timeout=600)
        else:
            log(f"⏸️  strategy_picks 等 19:00 strategy_sync 自动跑")

    # 2d. kline_api_sample → 重跑 data 后自然恢复
    if any(k.startswith("kline_api_sample") for k in failed) and not retried:
        log("\n--- 重试 data_update (kline_api_sample 失败) ---")
        retried = True
        exec_cmd(f"{PYTHON} {BACKEND}/scripts/data_update.py", timeout=7200)

    # 2e. backend_alive → 重启
    if any(k.startswith("backend_alive") for k in failed):
        log("\n--- 重启 a-stock-backend ---")
        retried = True
        exec_cmd("systemctl --user restart a-stock-backend.service")
        time.sleep(5)
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                           "http://localhost:9901/api/ping"], capture_output=True, text=True, timeout=10)
        log(f"后端 {r.stdout if r.stdout == '200' else '❌ ' + r.stdout}")

    # 3. 确认
    if retried:
        log("\n--- 重试后复检 ---")
        time.sleep(15)
        r2 = run_health()
        if r2 and r2.get("all_passed"):
            log("✅ 重试后全部通过")
        elif r2:
            still = get_failed(r2.get("checks", {}))
            log(f"⚠️  仍存 {len(still)} 项失败:\n" + "\n".join(
                f"   - {n}: {c.get('detail','')[:100]}" for n, c in still.items()))
        else:
            log("⚠️ 复检异常")
    else:
        log("ℹ️  无需重试")

    log(f"{'='*50}")
    return True

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
