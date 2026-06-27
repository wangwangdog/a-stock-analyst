#!/usr/bin/env python3
"""
全量A股前复权 + 成交额批量替换脚本
1. 遍历kline_cache所有daily标的
2. 从腾讯获取前复权K线 (最多300条)
3. volume列替换为成交额(元)
4. 并行处理+批量写入
"""
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HOME = Path.home()
DB_PATH = HOME / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"

MAX_WORKERS = 15       # 并发数
BATCH_SIZE = 50        # 每多少只股票写入一次DB
API_TIMEOUT = 25       # 腾讯API超时
TOTAL_LIMIT = 300      # 每只股票最多取300条


def get_symbol_mapping(conn) -> dict:
    """获取bare_code到symbol列表的映射"""
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT symbol FROM kline_cache WHERE period="daily"')
    all_symbols = [r[0] for r in cur.fetchall()]

    mapping = {}  # bare_code -> [(symbol, market_prefix), ...]
    for s in all_symbols:
        if '.' in s:
            prefix, code = s.split('.', 1)
            market = prefix.lower()  # sh/sz/bj
        else:
            code = s
            # 从股票代码判断市场
            if code.startswith(('6', '9')):
                market = 'sh'
            elif code.startswith(('0', '3')):
                market = 'sz'
            elif code.startswith('8'):
                market = 'bj'
            else:
                market = 'sz'  # 默认深证
        bare = code
        mapping.setdefault(bare, []).append((s, market))

    return mapping


def fetch_qfq(bare_code: str) -> tuple:
    """获取单只股票前复权数据，返回 (klines, amount_by_date) 或 (None, None)"""
    # 判断市场
    if bare_code.startswith(('6', '9')):
        market = 'sh'
    elif bare_code.startswith(('0', '3')):
        market = 'sz'
    elif bare_code.startswith('8'):
        market = 'bj'
    else:
        return None, None

    tencent_code = f"{market}{bare_code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,{TOTAL_LIMIT},qfq"

    try:
        result = subprocess.run(
            ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
            capture_output=True, text=True, timeout=API_TIMEOUT
        )
        d = json.loads(result.stdout)
        sd = d.get("data", {}).get(tencent_code, {})
        klines = sd.get("qfqday", [])
        if not klines:
            return None, None

        # 从qt字段提取成交额
        qt = sd.get("qt", {}).get(tencent_code, [])
        amount_by_date = {}

        # qt[35]格式: "price/volume/amount"
        for item in qt:
            if isinstance(item, str) and '/' in item and item.count('/') == 2:
                parts = item.split('/')
                try:
                    price = float(parts[0])
                    amt = float(parts[2])
                    if amt > 1000000:
                        # 匹配收盘价找到对应日期
                        for k in reversed(klines):
                            close = float(k[2])
                            if abs(close - price) / max(close, 0.01) < 0.001:
                                amount_by_date[k[0]] = int(amt)
                                break
                except:
                    pass

        return klines, amount_by_date
    except Exception as e:
        return None, None


def process_stock(bare_code: str, symbols: list, conn: sqlite3.Connection) -> dict:
    """
    处理单只股票
    返回: {"bare_code": xxx, "ok": True/False, "symbols": updated_symbols, "rows": count, "error": msg}
    """
    klines, amounts = fetch_qfq(bare_code)
    if klines is None:
        return {"bare_code": bare_code, "ok": False, "symbols": [], "rows": 0, "error": "no_data"}

    # 准备数据：计算成交额
    rows_to_insert = []
    for symbol, _ in symbols:
        for k in klines:
            date_str = k[0]
            o, c, h, l = float(k[1]), float(k[2]), float(k[3]), float(k[4])
            vol_hands = float(k[5])
            amt = amounts.get(date_str, int(vol_hands * 100 * ((o + c) / 2)))
            rows_to_insert.append((symbol, "tencent_fq", "daily", date_str,
                                    o, c, h, l, amt, amt))

    # 写入数据库 (使用调用者传入的conn)
    cursor = conn.cursor()
    # 先删旧数据
    placeholders = ','.join(['?'] * len(symbols))
    sym_list = [s[0] for s in symbols]
    cursor.execute(
        f"DELETE FROM kline_cache WHERE symbol IN ({placeholders}) AND period='daily'",
        sym_list
    )

    # 批量插入
    cursor.executemany(
        """INSERT INTO kline_cache 
           (symbol, source, period, trade_date, open, close, high, low, volume, amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows_to_insert
    )
    conn.commit()

    return {
        "bare_code": bare_code,
        "ok": True,
        "symbols": [s[0] for s in symbols],
        "rows": len(rows_to_insert),
        "error": None
    }


def main():
    print("=" * 60)
    print("全量A股 前复权+成交额 批量替换")
    print(f"并发数: {MAX_WORKERS}, 单批: {BATCH_SIZE}")
    print()

    # 连接DB
    conn = sqlite3.connect(str(DB_PATH))
    mapping = get_symbol_mapping(conn)

    bare_items = list(mapping.items())
    total = len(bare_items)
    print(f"共 {total} 只唯一股票 (对应 {len(set(s for syms in mapping.values() for s, _ in syms))} 个symbol变体)")

    # 过滤掉指数
    index_codes = set()
    for bare, syms in mapping.items():
        for s, m in syms:
            if s.startswith(('SH.', 'SZ.')):
                code = s.split('.')[1]
                if code.startswith(('0', '1', '399', '880', '159')) and len(code) >= 6:
                    if code.startswith(('399', '159', '880')):
                        index_codes.add(bare)
                        break

    # 保留所有，让腾讯API自己决定能否返回数据
    # 指数返回的qfqday可能是None，自动跳过

    success = 0
    failed = 0
    total_rows = 0
    start_time = time.time()

    # 并行处理
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        # 分批提交
        for i in range(0, total, BATCH_SIZE):
            batch = bare_items[i:i + BATCH_SIZE]
            for bare_code, symbols in batch:
                # 每个任务用独立连接
                def task(code=bare_code, syms=symbols):
                    local_conn = sqlite3.connect(str(DB_PATH))
                    try:
                        return process_stock(code, syms, local_conn)
                    finally:
                        local_conn.close()
                future = executor.submit(task)
                futures[future] = (bare_code, symbols)

            # 等待这一批完成
            for future in as_completed(futures):
                result = future.result()
                if result["ok"]:
                    success += 1
                    total_rows += result["rows"]
                else:
                    failed += 1

            # 清空已完成的future
            futures = {}

            # 进度报告
            elapsed = time.time() - start_time
            done = success + failed
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(f"  [{done}/{total}] 成功:{success} 失败:{failed} 行:{total_rows:,} "
                  f"速率:{rate:.1f}股/秒 ETA:{eta:.0f}s")

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"✅ 完成! 耗时 {elapsed:.0f}s")
    print(f"   成功: {success} 只")
    print(f"   失败: {failed} 只")
    print(f"   写入: {total_rows:,} 条K线")

    # 最终验证
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM kline_cache WHERE period="daily" AND source="tencent_fq"')
    fq_done = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM kline_cache WHERE period="daily"')
    total_daily = cur.fetchone()[0]
    print(f"   前复权数据: {fq_done:,} / {total_daily:,} 条")

    # 显示几个样本
    cur.execute('''
        SELECT symbol, trade_date, open, close, volume, amount 
        FROM kline_cache WHERE period="daily" AND source="tencent_fq"
        ORDER BY RANDOM() LIMIT 5
    ''')
    print("\n随机样本:")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]} O:{r[2]:.2f} C:{r[3]:.2f} Vol(成交额):{r[4]:>15,} Amt:{r[5]:>15,}")

    conn.close()


if __name__ == "__main__":
    main()
