#!/usr/bin/env python3
"""
SZ.000001 (平安银行) 前复权 + 成交额同步脚本
1. 获取 前复权 K线数据
2. 将 volume（成交量 手）替换为 成交额（元）
"""
import json
import sqlite3
import subprocess
from pathlib import Path

HOME = Path.home()
DB_PATH = Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")

def fetch_tencent_fq(symbol: str, count: int = 300) -> tuple:
    """
    从腾讯获取前复权数据，返回 (klines_list, amount_list)
    klines_list: [(date, open, close, high, low, volume_hands), ...]
    amount_list: [(date, amount_yuan), ...]
    """
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
    result = subprocess.run(
        ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True, text=True, timeout=30
    )
    d = json.loads(result.stdout)
    sd = d["data"][symbol]
    klines = sd["qfqday"]  # [[date, open, close, high, low, volume], ...]
    
    # 从 qt 字段提取成交额
    qt = sd.get("qt", {}).get(symbol, [])
    # 找 "price/volume/amount" 格式的字符串
    amounts = {}
    for item in qt:
        if isinstance(item, str) and '/' in item:
            parts = item.split('/')
            if len(parts) == 3 and all(p.replace('.','').replace('-','').isdigit() for p in parts):
                amount_yuan = int(float(parts[2]))
                # 对应日期需要从 klines 找
                break
    
    # 另一种方式：从 qt 找成交额(万元)字段
    # 对于SZ股票，qt[57]是成交额(万元)
    amount_wan = None
    for i, item in enumerate(qt):
        if isinstance(item, str) and item.replace('.','').isdigit():
            try:
                val = float(item)
                if 10000 < val < 10000000:  # 1亿~1000亿范围，可能是成交额(万元)
                    amount_wan = val
                    # 取最大的那个（排除其他小数字）
            except:
                pass
    
    # 更精确：从价格/量/额 字段找
    # qt[35] 格式: "11.03/1090926/1203946343"
    amount_by_date = {}
    for item in qt:
        if isinstance(item, str) and '/' in item and item.count('/') == 2:
            parts = item.split('/')
            try:
                price = float(parts[0])
                vol = float(parts[1])
                amt = float(parts[2])
                if price > 1 and amt > 1000000:
                    # 计算这条数据对应的日期：从最后一条K线开始匹配
                    # 用当前收盘价匹配
                    for k in reversed(klines):
                        close = float(k[2])
                        if abs(close - price) / close < 0.001:
                            amount_by_date[k[0]] = int(amt)
                            break
            except:
                pass
    
    return klines, amount_by_date

def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    print("=" * 60)
    print("获取 SZ.000001 (平安银行) 前复权数据...")
    klines, amounts = fetch_tencent_fq("sz000001", 300)
    if not klines:
        print("❌ 获取失败")
        return
    
    print(f"✅ {len(klines)} 条前复权 K线")
    print(f"   范围: {klines[0][0]} ~ {klines[-1][0]}")
    print(f"   带成交额的数据: {len(amounts)} 条")
    
    # 显示匹配情况
    match_count = 0
    for k in klines:
        if k[0] in amounts:
            match_count += 1
    print(f"   成交额匹配: {match_count}/{len(klines)}")
    
    # 如果匹配不足，用推算方法
    if match_count < len(klines) * 0.5:
        print("   成交额匹配不足，用成交量推算...")
        # 成交额(元) = 成交量(手) × 100 × 均价
        # 均价 ≈ (open + close) / 2
        for k in klines:
            if k[0] not in amounts:
                vol_hands = float(k[5])
                avg_price = (float(k[1]) + float(k[2])) / 2
                amounts[k[0]] = int(vol_hands * 100 * avg_price)
    
    # 删除旧数据
    cur.execute("DELETE FROM kline_cache WHERE symbol='SZ.000001' AND period='daily'")
    deleted = cur.rowcount
    conn.commit()
    print(f"   已删除 {deleted} 条旧数据")
    
    # 写入新数据：volume = 成交额(元)
    inserted = 0
    for k in klines:
        date_str = k[0]
        o, c, h, l = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        vol_hands = int(float(k[5]))
        amt = amounts.get(date_str, int(vol_hands * 100 * ((o + c) / 2)))
        
        cur.execute(
            """INSERT INTO kline_cache 
               (symbol, source, period, trade_date, open, close, high, low, volume, amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SZ.000001", "tencent_fq", "daily", date_str,
             o, c, h, l, amt, amt)  # volume = amount = 成交额(元)
        )
        inserted += 1
    conn.commit()
    print(f"   已写入 {inserted} 条")
    
    # 验证
    cur.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM kline_cache WHERE symbol='SZ.000001' AND period='daily'"
    )
    cnt, mn, mx = cur.fetchone()
    cur.execute(
        "SELECT trade_date, open, close, volume, amount FROM kline_cache WHERE symbol='SZ.000001' AND period='daily' ORDER BY trade_date DESC LIMIT 3"
    )
    print(f"\n验证: {cnt} 条 ({mn} ~ {mx})")
    print("最新3条 (volume=成交额元):")
    for r in cur.fetchall():
        print(f"  {r[0]} O:{r[1]:.2f} C:{r[2]:.2f} Vol(成交额):{r[3]:>15,} Amt:{r[4]:>15,}")
    
    conn.close()
    print("=" * 60)
    print("✅ 完成")

if __name__ == "__main__":
    main()
