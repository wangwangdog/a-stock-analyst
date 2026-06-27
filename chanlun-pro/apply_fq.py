#!/usr/bin/env python3
"""
前复权替换脚本：将 SZ.000001 (平安银行) 的 kline_cache daily 数据替换为前复权。
从腾讯行情API获取前复权K线数据。

说明：
- SH.000001 (上证指数) 是指数，无复权概念，不修改
- SZ.000001 (平安银行) 有分红送股历史，需要前复权
- 腾讯API最多返回300条，取最新300个交易日的前复权数据
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
DB_PATH = HOME / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"


def fetch_tencent_qfq(symbol: str, count: int = 300) -> list:
    """从腾讯行情获取前复权日K线"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
    result = subprocess.run(
        ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True, text=True, timeout=30
    )
    d = json.loads(result.stdout)
    data = d.get("data", {})
    # 腾讯返回嵌套格式：data.{code}.qfqday
    stock_data = data.get(symbol, {})
    klines = stock_data.get("qfqday", [])
    return klines


def fetch_tencent_raw(symbol: str, count: int = 300) -> list:
    """从腾讯行情获取不复权（未调整）日K线"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},"
    result = subprocess.run(
        ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True, text=True, timeout=30
    )
    d = json.loads(result.stdout)
    stock_data = d.get("data", {}).get(symbol, {})
    klines = stock_data.get("day", [])
    return klines


def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # === SZ.000001 平安银行 ===
    print("=" * 60)
    print("下载 SZ.000001 (平安银行) 前复权数据...")
    fq_klines = fetch_tencent_qfq("sz000001", 300)
    if not fq_klines:
        print("❌ 获取前复权数据失败")
        sys.exit(1)
    print(f"✅ 获取到 {len(fq_klines)} 条前复权数据")
    print(f"   日期范围: {fq_klines[0][0]} ~ {fq_klines[-1][0]}")

    # 显示前复权 vs 不复权对比
    raw_klines = fetch_tencent_raw("sz000001", 300)
    print(f"   不复权数据: {len(raw_klines)} 条")

    # 首个交易日前复权/不复权比率
    if raw_klines and fq_klines:
        r_first = float(raw_klines[0][4])
        f_first = float(fq_klines[0][4])
        factor = f_first / r_first if r_first > 0 else 1
        print(f"   最早复权因子: {factor:.6f}")

    # 删除旧的 daily 数据 (不复权)
    cur.execute("DELETE FROM kline_cache WHERE symbol='SZ.000001' AND period='daily'")
    deleted = cur.rowcount
    conn.commit()
    print(f"   已删除 {deleted} 条不复权 daily 数据")

    # 写入前复权数据
    # 腾讯格式: [date, open, close, high, low, volume]
    # kline_cache: symbol, source, period, trade_date, open, close, high, low, volume, amount
    inserted = 0
    for k in fq_klines:
        date_str = k[0]
        open_p = float(k[1])
        close_p = float(k[2])
        high_p = float(k[3])
        low_p = float(k[4])
        vol = int(float(k[5]))  # 腾讯成交量单位: 手
        # 成交额 = 成交量(股) × 均价 ≈ 成交量(手) × 100 × close
        amount = int(vol * 100 * close_p)

        cur.execute(
            """INSERT INTO kline_cache 
               (symbol, source, period, trade_date, open, close, high, low, volume, amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SZ.000001", "tencent_fq", "daily", date_str,
             open_p, close_p, high_p, low_p, vol, amount)
        )
        inserted += 1
    conn.commit()
    print(f"   已写入 {inserted} 条前复权 daily 数据到 kline_cache")

    # 验证
    cur.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM kline_cache WHERE symbol='SZ.000001' AND period='daily'"
    )
    cnt, mn, mx = cur.fetchone()
    print(f"   验证: SZ.000001 daily 共 {cnt} 条 ({mn} ~ {mx})")

    # 检查最新数据价格（应为~10-11平安银行股票价格）
    cur.execute(
        "SELECT trade_date, open, close, high, low FROM kline_cache WHERE symbol='SZ.000001' AND period='daily' ORDER BY trade_date DESC LIMIT 3"
    )
    print("   最新3条:")
    for r in cur.fetchall():
        print(f"      {r[0]} O:{r[1]} C:{r[2]} H:{r[3]} L:{r[4]}")

    # === SH.000001 上证指数（无复权概念，跳过） ===
    print()
    print("SH.000001 (上证指数): 指数无复权概念，跳过")

    conn.close()
    print("=" * 60)
    print("✅ 前复权替换完成")


if __name__ == "__main__":
    main()
