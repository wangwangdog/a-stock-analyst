#!/usr/bin/env python3
"""
全量补齐 A 股日线数据脚本 v3
- 从 all_stock_info 获取股票列表（含名称）
- 从腾讯前复权 API 拉取日线数据
- 写入 kline_cache（裸码 + 前缀码 SH./SZ.）
- 覆盖 2025-10-01 至今
"""
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 取消输出缓冲
print = lambda *a, **kw: __import__('builtins').print(*a, **kw, flush=True)

HOME = Path.home()
DB_PATH = HOME / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"
START_DATE = "2025-10-01"

MAX_WORKERS = 20
API_TIMEOUT = 25
TOTAL_LIMIT = 320  # 约 14 个月交易日
PROGRESS_INTERVAL = 200


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_stock_list(conn):
    """获取 A 股股票列表 (0/3/6/9 打头)，含名称"""
    rows = conn.execute(
        "SELECT symbol, name FROM all_stock_info "
        "WHERE substr(symbol,1,1) IN ('0','3','6','9') "
        "ORDER BY symbol"
    ).fetchall()
    print(f"📋 待处理 A 股: {len(rows)} 只")
    return rows


def code_prefix(bare: str) -> str:
    """裸码 → 交易所前缀"""
    if bare.startswith(("6", "9", "68")):
        return "SH"
    if bare.startswith(("0", "3", "002", "200", "300", "301")):
        return "SZ"
    if bare.startswith(("8", "4", "920")):
        return "BJ"
    return ""


def fetch_one(bare_code: str, name: str) -> dict:
    """拉取一只股票的前复权日线数据"""
    prefix = code_prefix(bare_code)
    if not prefix:
        return {"bare": bare_code, "ok": False, "err": f"unknown_prefix:{bare_code}"}

    market = prefix.lower()
    tencent_code = f"{market}{bare_code}"
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/"
        f"get?param={tencent_code},day,,,{TOTAL_LIMIT},qfq"
    )

    for attempt in range(2):
        try:
            result = subprocess.run(
                ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
                capture_output=True, text=True, timeout=API_TIMEOUT,
            )
            d = json.loads(result.stdout)
            sd = d.get("data", {}).get(tencent_code, {})
            klines = sd.get("qfqday", [])
            if not klines:
                # 没前复权数据，尝试不复权
                klines = sd.get("day", [])
            if not klines:
                return {"bare": bare_code, "ok": False, "err": "no_data"}

            # 从 qt 段提取成交额
            qt = sd.get("qt", {}).get(tencent_code, [])
            amounts = {}
            for item in qt:
                if isinstance(item, str) and "/" in item and item.count("/") == 2:
                    parts = item.split("/")
                    try:
                        price, vol, amt = float(parts[0]), float(parts[1]), float(parts[2])
                        if amt > 10000:
                            for k in reversed(klines):
                                if abs(float(k[2]) - price) / max(float(k[2]), 0.01) < 0.001:
                                    amounts[k[0]] = int(amt)
                                    break
                    except Exception:
                        pass

            # 过滤 2025-10-01 之后的数据
            rows = []
            for k in klines:
                date = k[0]
                if date < START_DATE:
                    continue
                o, c, h, l = float(k[1]), float(k[2]), float(k[3]), float(k[4])
                vh = float(k[5])  # 手数
                vol_shares = int(vh * 100)  # 转股数
                amt = amounts.get(date, int(vh * 100 * ((o + c) / 2)))
                rows.append((date, o, c, h, l, vol_shares, amt))

            return {
                "bare": bare_code,
                "name": name,
                "prefix": prefix,
                "ok": True,
                "rows": rows,
            }

        except json.JSONDecodeError:
            return {"bare": bare_code, "ok": False, "err": "json_decode"}
        except subprocess.TimeoutExpired:
            if attempt == 0:
                continue
            return {"bare": bare_code, "ok": False, "err": "timeout"}
        except Exception as e:
            if attempt == 0:
                continue
            return {"bare": bare_code, "ok": False, "err": str(e)}

    return {"bare": bare_code, "ok": False, "err": "max_retry"}


def write_batch(conn, results):
    """批量写入 kline_cache，同时更新 all_stock_info 名称"""
    cur = conn.cursor()
    total = 0
    updated_names = 0

    for r in results:
        if not r["ok"]:
            continue

        bare = r["bare"]
        name = r["name"]
        prefix = r["prefix"]
        prefixed = f"{prefix}.{bare}"

        # 更新 all_stock_info 中的名称（如果缺失）
        cur.execute(
            "UPDATE all_stock_info SET name=? WHERE symbol=? AND (name IS NULL OR name='')",
            (name, bare),
        )
        if cur.rowcount > 0:
            updated_names += 1

        # 删除旧数据（两种符号都删）
        for sym in (bare, prefixed):
            cur.execute(
                "DELETE FROM kline_cache WHERE symbol=? AND period='daily'",
                (sym,),
            )

            # 插入新数据
            insert_rows = [
                (sym, "tencent_fq", "daily", date, o, c, h, l, vol, amt, name)
                for date, o, c, h, l, vol, amt in r["rows"]
            ]
            cur.executemany(
                "INSERT INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount, name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                insert_rows,
            )
        total += len(r["rows"])

    conn.commit()
    return total, updated_names


def main():
    t_start = time.time()

    # 检查 kline_cache 是否有 name 列
    conn = get_db()
    cur = conn.cursor()
    cols = [row[1] for row in cur.execute("PRAGMA table_info(kline_cache)").fetchall()]
    if "name" not in cols:
        print("📦 添加 name 列到 kline_cache...")
        cur.execute("ALTER TABLE kline_cache ADD COLUMN name TEXT DEFAULT ''")
        conn.commit()
        print("   ✅ name 列已添加")

    stocks = get_stock_list(conn)
    conn.close()

    total = len(stocks)
    success = failed = 0
    total_rows = 0

    # 并发拉取
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_one, code, name): (code, name)
            for code, name in stocks
        }

        write_buffer = []
        done = 0

        for future in as_completed(futures):
            result = future.result()
            done += 1

            if result["ok"]:
                write_buffer.append(result)
                success += 1
            else:
                failed += 1
                err = result.get("err", "?")
                if failed <= 20:
                    print(f"  ❌ {result['bare']}: {err}")

            # 每 20 只或最后一批写入
            if len(write_buffer) >= 20 or done == total:
                if write_buffer:
                    conn = get_db()
                    n, name_upd = write_batch(conn, write_buffer)
                    total_rows += n
                    conn.close()
                    write_buffer = []

            # 进度报告
            if done % PROGRESS_INTERVAL == 0 or done == total:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(
                    f"  [{done}/{total}] ✅{success} ❌{failed} "
                    f"行:{total_rows:,} 速率:{rate:.1f}/s ETA:{eta:.0f}s"
                )

        # 最后一批
        if write_buffer:
            conn = get_db()
            n, name_upd = write_batch(conn, write_buffer)
            total_rows += n
            conn.close()

    elapsed = time.time() - t_start
    print()
    print("=" * 60)
    print(f"✅ 完成! 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"   成功: {success}  失败: {failed}")
    print(f"   写入: {total_rows:,} 条 K 线")

    # 最终验证
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM kline_cache WHERE period='daily' "
        "AND trade_date >= ? AND source='tencent_fq'",
        (START_DATE,),
    )
    final_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period='daily' "
        "AND trade_date >= ? AND source='tencent_fq'",
        (START_DATE,),
    )
    final_stocks = cur.fetchone()[0]

    # 检查 volume==amount 的残留
    cur.execute(
        "SELECT COUNT(*) FROM kline_cache WHERE period='daily' "
        "AND source='tencent_fq' AND volume=amount"
    )
    bad = cur.fetchone()[0]

    print(f"\n📊 最终验证:")
    print(f"   kline_cache daily (tencent_fq, {START_DATE}~至今):")
    print(f"     记录: {final_count:,} 条")
    print(f"     股票: {final_stocks} 只")
    print(f"     volume=amount 残留: {bad} 条 {'✅' if bad==0 else '❌'}")
    conn.close()


if __name__ == "__main__":
    main()
