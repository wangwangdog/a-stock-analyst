#!/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/.venv/bin/python3
"""
从通达信(TDX)实时行情接口同步分钟K线数据到本地 kline_cache 表

用法：
    ./sync_tdx_minute.py                    # 增量更新 5m/15m/30m/60m
    ./sync_tdx_minute.py --freq 5m          # 只更新 5分钟
    ./sync_tdx_minute.py --freq 15m,30m     # 更新多个频率
    ./sync_tdx_minute.py --freq all         # 全部频率
    ./sync_tdx_minute.py --force            # 强制全量重载

TDX 分类码：
    0=5分钟, 1=15分钟, 2=30分钟, 3=60分钟, 7=日线, 8=1分钟
"""
import sys
import os
import json
import time
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pytdx.hq import TdxHq_API

# ── 配置 ──────────────────────────────────────────────────────────
TDX_FREQ_MAP = {
    "5m":  {"cat": 0, "limit": 800},
    "15m": {"cat": 1, "limit": 800},
    "30m": {"cat": 2, "limit": 800},
    "60m": {"cat": 3, "limit": 800},
}

# stock_market 映射: code 前缀 → TDX market code
def get_tdx_market(code: str) -> int:
    """返回 TDX 市场代码: 0=深圳, 1=上海, 2=北京"""
    code = str(code).strip()
    if code.startswith('6') or code.startswith('9'):
        return 1  # 上海
    if code.startswith('8') or code.startswith('4'):
        return 2  # 北京
    return 0  # 深圳 (0xxx, 3xxx)

# 数据库路径
DB_PATH = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))

# ── 工具 ──────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} | {msg}", flush=True)


def find_best_tdx_ip() -> dict:
    """查找最佳 TDX 行情服务器"""
    try:
        from pytdx.config import hq_hosts
    except ImportError:
        from pytdx.config.hosts import hq_hosts

    best = None
    best_time = float('inf')
    for host in hq_hosts:
        # pytdx 不同版本格式: dict 或 tuple
        if isinstance(host, tuple):
            ip, port = host[1], host[2] if len(host) > 2 else 7709
        else:
            ip = host.get('ip', host)
            port = host.get('port', 7709)
        try:
            api = TdxHq_API()
            api.connect(ip, port)
            start = time.time()
            _ = api.get_security_count(0)
            elapsed = time.time() - start
            api.disconnect()
            if elapsed < best_time:
                best_time = elapsed
                best = {"ip": ip, "port": int(port)}
        except:
            continue

    if best is None:
        # fallback: known working server
        best = {"ip": "180.153.18.170", "port": 7709}
    return best


def get_all_stocks() -> list:
    """从数据库获取全量A股股票列表"""
    conn = sqlite3.connect(DB_PATH)
    # 先尝试 symbol 列，再尝试 code 列
    cur = conn.execute("PRAGMA table_info(all_stock_info)")
    cols = [r[1] for r in cur.fetchall()]
    col = "symbol" if "symbol" in cols else "code"

    cur = conn.execute(
        f"SELECT {col} FROM all_stock_info WHERE {col} IS NOT NULL ORDER BY {col}"
    )
    stocks = [str(row[0]).strip() for row in cur.fetchall() if row[0]]
    conn.close()
    # 仅保留A股格式（6位数字代码）
    stocks = [s for s in stocks if s.isdigit() and len(s) == 6]
    if not stocks:
        log("⚠️  数据库中未找到股票列表")
    return stocks


def get_last_date(symbol: str, period: str) -> str | None:
    """获取 kline_cache 中该股票该周期的最后交易日"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period=? AND source='tdx'",
        (symbol, period)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def save_klines(symbol: str, period: str, df_rows: list):
    """批量写入 kline_cache 表（INSERT OR IGNORE，不写已存在的数据）"""
    if not df_rows:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
        "VALUES (?, 'tdx', ?, ?, ?, ?, ?, ?, ?, ?)",
        df_rows
    )
    conn.commit()
    conn.close()


def fetch_and_save(api: TdxHq_API, code: str, freq: str, freq_cat: int, pages: int = 6):
    """拉取一只股票指定频率的 K 线数据并保存"""
    market = get_tdx_market(code)
    try:
        # 通达信 get_security_bars(category, market, code, start, count)
        all_bars = []
        for i in range(1, pages + 1):
            bars = api.get_security_bars(freq_cat, market, code, (i - 1) * 700, 700)
            if not bars:
                break
            all_bars.extend(bars)

        if not all_bars:
            return 0

        rows = []
        for bar in all_bars:
            # pytdx 返回的时间格式: 可能是 datetime 对象或字符串
            raw_dt = bar.get("datetime") or bar.get("time")
            if raw_dt is None:
                continue
            if hasattr(raw_dt, "strftime"):
                trade_date = raw_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                trade_date = str(raw_dt).strip()
            rows.append((
                code,
                freq,
                trade_date,
                float(bar.get("open", 0)),
                float(bar.get("close", 0)),
                float(bar.get("high", 0)),
                float(bar.get("low", 0)),
                float(bar.get("vol", 0) or 0),
                float(bar.get("amount", 0) or 0),
            ))

        if rows:
            save_klines(code, freq, rows)

        return len(rows)
    except Exception as e:
        return -1


# ── 主流程 ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="从通达信同步分钟K线数据")
    parser.add_argument("--freq", default="5m,15m,30m,60m",
                        help="频率列表，逗号分隔，如 '5m,15m' 或 'all' 或 '5m'")
    parser.add_argument("--force", action="store_true",
                        help="强制全量重载（忽略已有数据）")
    parser.add_argument("--pages", type=int, default=4,
                        help="每个股票拉取页数（每页700条），默认4页(2800条)")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理的股票数（调试用，0=不限）")
    args = parser.parse_args()

    # 解析频率
    if args.freq == "all":
        freqs = list(TDX_FREQ_MAP.keys())
    else:
        freqs = [f.strip() for f in args.freq.split(",") if f.strip() in TDX_FREQ_MAP]
    if not freqs:
        log(f"❌ 无效频率: {args.freq}，可选: {list(TDX_FREQ_MAP.keys())}")
        sys.exit(1)

    # 获取股票列表
    all_stocks = get_all_stocks()
    if not all_stocks:
        log("❌ 未获取到股票列表，退出")
        sys.exit(1)
    log(f"📋 共 {len(all_stocks)} 只股票")

    # 如果设了 limit，截断
    if args.limit and 0 < args.limit < len(all_stocks):
        all_stocks = all_stocks[:args.limit]
        log(f"🔧 调试模式: 仅处理 {args.limit} 只")

    # 连接 TDX（使用已知可用服务器，避免热启动耗时）
    conn_info = {"ip": "180.153.18.170", "port": 7709}
    log(f"🔌 连接 TDX: {conn_info['ip']}:{conn_info['port']}")

    api = TdxHq_API(raise_exception=True, auto_retry=True)
    try:
        api.connect(conn_info["ip"], conn_info["port"])
        log("✅ 已连接 TDX 行情服务器")
    except Exception as e:
        log(f"❌ 连接失败: {e}")
        sys.exit(1)

    try:
        for freq in freqs:
            freq_config = TDX_FREQ_MAP[freq]
            log(f"\n{'='*50}")
            log(f"📊 开始同步 {freq} 数据 (category={freq_config['cat']})")
            log(f"{'='*50}")

            total_ok = 0
            total_fail = 0
            total_skip = 0
            start_t = time.time()

            for idx, code in enumerate(all_stocks):
                code = str(code).strip()

                # 跳过已有最新数据的（增量模式）
                if not args.force:
                    last_date = get_last_date(code, freq)
                    if last_date:
                        # 检查是否已包含最新交易日
                        trade_date_part = last_date[:10]
                        # 周六日的话，取周五
                        now = datetime.now()
                        weekday = now.weekday()
                        if weekday == 5:  #周六
                            latest_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                        elif weekday == 6:  #周日
                            latest_day = (now - timedelta(days=2)).strftime("%Y-%m-%d")
                        else:
                            latest_day = now.strftime("%Y-%m-%d")
                        # 只跳过当天（避免重复），其他日期正常同步
                        if trade_date_part == latest_day:
                            total_skip += 1
                            continue
                        # 删除硬编码日期判断，允许同步所有历史数据

                bars = fetch_and_save(api, code, freq, freq_config["cat"], pages=args.pages)
                if bars < 0:
                    total_fail += 1
                else:
                    total_ok += 1

                if (idx + 1) % 500 == 0 or idx == len(all_stocks) - 1:
                    elapsed = time.time() - start_t
                    log(f"  {freq}: {idx+1}/{len(all_stocks)} "
                        f"(✅{total_ok} ❌{total_fail} ⏭{total_skip}) "
                        f"耗时 {elapsed:.0f}s")

            elapsed = time.time() - start_t
            log(f"✅ {freq} 完成: 更新{total_ok} 失败{total_fail} 跳过{total_skip} "
                f"耗时 {elapsed:.0f}s")

    finally:
        api.close()
        log("🔌 已断开 TDX 连接")


if __name__ == "__main__":
    main()
