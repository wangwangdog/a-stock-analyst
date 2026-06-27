#!/usr/bin/env python3
"""
今日日线补充：只补今天（2026-05-25）缺失的日线数据
特点：WAL 模式 + busy_timeout=30s，不锁死数据库
      数据源：腾讯行情 API（稳定快速）+ AKShare 兜底
      批量查询：50只股票/请求，100只/批次写入
"""
import sys
import sqlite3
import time
import os
import signal
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar

# 配置
DB_PATH = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')
TODAY = datetime.now().strftime('%Y-%m-%d')
TENCENT_BATCH = 50       # 每批查询50只股票
MAX_WORKERS = 4          # 4个并发批处理
BATCH_SIZE = 100         # 每100只写入一次DB
TENCENT_TIMEOUT = 10
AKSHARE_TIMEOUT = 20

cal = get_calendar()
stop_event = False
success_count = 0
failed_count = 0


def signal_handler(sig, frame):
    global stop_event
    stop_event = True
    print("\n[收到停止信号] 完成当前批次后退出...")

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_conn():
    """WAL 模式 + busy_timeout，不锁库"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_missing_symbols():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT DISTINCT symbol FROM stock_daily WHERE date = ?', (TODAY,))
    existing = {row[0] for row in cursor.fetchall()}
    cursor.execute('SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol')
    all_symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    missing = [s for s in all_symbols if s not in existing]
    print(f"📊 总股票数: {total:,}")
    print(f"✅ 今日已有: {len(existing):,}")
    print(f"❌ 今日缺失: {len(missing):,}")
    return missing


def symbol_to_tx_code(symbol: str) -> str:
    """转腾讯行情代码：sh/sz 前缀"""
    if symbol.startswith(("6", "68", "9")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def fetch_tencent_batch(symbols: list) -> list:
    """从腾讯行情批量拉取今日数据"""
    if not symbols:
        return []
    codes = [symbol_to_tx_code(s) for s in symbols]
    url = "http://qt.gtimg.cn/q=" + ",".join(codes)

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Referer": "https://qt.gtimg.cn",
        })
        with urllib.request.urlopen(req, timeout=TENCENT_TIMEOUT) as resp:
            raw = resp.read().decode("gbk")
    except Exception:
        return []

    rows = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        try:
            # 提取引号内内容
            data = line.split('"')[1] if '"' in line else ""
            fields = data.split("~")
            if len(fields) < 35:
                continue

            code = fields[2].strip()
            close = float(fields[3]) if fields[3] else 0
            yclose = float(fields[4]) if fields[4] else 0
            open_p = float(fields[5]) if fields[5] else 0
            volume_lots = float(fields[6]) if fields[6] else 0  # 手
            high = float(fields[33]) if fields[33] else 0
            low = float(fields[34]) if fields[34] else 0

            if close <= 0:
                continue

            volume = volume_lots * 100
            # 成交额解析：字段35含 "price/volume/amount"
            amount = 0
            if len(fields) > 35 and '/' in fields[35]:
                parts = fields[35].split('/')
                if len(parts) >= 3 and parts[2]:
                    try:
                        amount = float(parts[2])
                    except ValueError:
                        pass
            if amount <= 0 and len(fields) > 37 and fields[37]:
                try:
                    amount = float(fields[37]) * 10000  # 万元→元
                except ValueError:
                    pass
            if amount <= 0:
                amount = volume * close  # 估算

            # 解析日期。字段30通常是 20260525161404 格式（或类似）
            # 也可能只有日期部分
            date_str = TODAY  # 今天是交易日，用 TODAY

            rows.append([code, date_str, open_p, high, low, close, volume, amount])
        except (ValueError, IndexError):
            continue

    return rows


def fetch_akshare_fallback(symbol: str) -> list:
    """AKShare 兜底（单个股票拉取）"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=TODAY.replace('-', ''),
            end_date=TODAY.replace('-', ''),
            adjust="qfq",
            timeout=AKSHARE_TIMEOUT
        )
        if df is not None and not df.empty:
            rows = []
            for _, row in df.iterrows():
                rows.append([
                    symbol, row['日期'], row['开盘'], row['最高'], row['最低'],
                    row['收盘'], row['成交量'], row['成交额']
                ])
            return rows
    except Exception:
        pass
    return []


def write_to_db(data):
    if not data:
        return
    conn = get_conn()
    cursor = conn.cursor()
    cursor.executemany(
        'INSERT OR REPLACE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        data
    )
    conn.commit()
    conn.close()


def main():
    global success_count, failed_count

    if not cal.is_trading_day(TODAY):
        print(f"⏭️  {TODAY} 不是交易日，无需补充")
        return

    print(f"🔍 开始补充 {TODAY} 日线数据...")
    print(f"   数据源: 腾讯行情(主) -> AKShare(兜底)")
    print(f"   批量: {TENCENT_BATCH}只/请求, {BATCH_SIZE}只/写入")
    print(f"   WAL模式: ✅ 不锁死数据库\n")

    missing_symbols = get_missing_symbols()
    if not missing_symbols:
        print("✅ 今日数据已全部补充完毕")
        return

    total = len(missing_symbols)
    print(f"\n🚀 开始拉取 {total:,} 只股票... (Ctrl+C 停止)\n")

    # 分批：每批 TENCENT_BATCH 只，并行 MAX_WORKERS 批
    batches = [missing_symbols[i:i + TENCENT_BATCH] for i in range(0, total, TENCENT_BATCH)]

    batch_data = []
    total_batches = len(batches)
    completed_stocks = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            if stop_event:
                break
            future = executor.submit(fetch_tencent_batch, batch)
            futures[future] = (i, batch)

        for future in as_completed(futures):
            if stop_event:
                break
            batch_idx, batch_symbols = futures[future]
            result = future.result()

            if result:
                success_count += len(result)
                batch_data.extend(result)
                # 标记腾讯失败的需要兜底
                ok_symbols = {r[0] for r in result}
                failed_in_batch = [s for s in batch_symbols if s not in ok_symbols]
            else:
                failed_in_batch = batch_symbols

            completed_stocks += len(batch_symbols)

            # 腾讯没拉到的，用 AKShare 兜底
            if failed_in_batch and not stop_event:
                for sym in failed_in_batch[:5]:  # 最多5只AKShare兜底（慢）
                    if stop_event:
                        break
                    aks_rows = fetch_akshare_fallback(sym)
                    if aks_rows:
                        success_count += 1
                        batch_data.extend(aks_rows)
                    else:
                        failed_count += 1
                # 超过5只的剩余股票直接记失败
                remaining_fails = len(failed_in_batch) - min(len(failed_in_batch), 5)
                if remaining_fails > 0:
                    failed_count += remaining_fails

            # 写DB
            if completed_stocks % BATCH_SIZE < len(batch_symbols) or completed_stocks >= total:
                if batch_data:
                    print(f"💾 写入批次 (累计{completed_stocks}/{total}, {len(batch_data)}条)...")
                    write_to_db(batch_data)
                    batch_data = []
                rate = success_count / (success_count + failed_count) * 100 if (success_count + failed_count) > 0 else 0
                print(f"   进度: {completed_stocks}/{total}, 成功率: {rate:.1f}% ({success_count}成功/{failed_count}失败)")
                time.sleep(1)

        if batch_data:
            print(f"💾 写入最后批次 ({len(batch_data)} 条)...")
            write_to_db(batch_data)

    if stop_event:
        print(f"\n⚠️  提前终止 (已处理 {completed_stocks}/{total})")
    else:
        print(f"\n✅ 补充完成")
    print(f"   成功: {success_count:,}")
    print(f"   失败: {failed_count:,}")
    if success_count + failed_count > 0:
        print(f"   成功率: {success_count/(success_count+failed_count)*100:.1f}%")

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date = ?', (TODAY,))
    final_count = cursor.fetchone()[0]
    conn.close()
    print(f"\n📊 最终 {TODAY} 数据: {final_count:,} 只股票")


if __name__ == "__main__":
    main()
