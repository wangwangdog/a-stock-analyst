#!/usr/bin/env python3
"""
补齐个股日线 2026-05-29 ~ 2026-06-04 缺失数据
使用腾讯行情API (0.06秒/次，快)
"""
import sys, os, sqlite3, re, requests, time, json

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
MISSING_DATES = {'2026-05-29', '2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04'}

def get_missing_stocks(conn):
    """获取需补齐的股票列表"""
    cur = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND trade_date='2026-05-28' AND source='baostock'"
    )
    all_stocks = [row[0] for row in cur.fetchall()]
    print(f"基准: {len(all_stocks)} 只")

    needs = []
    for stock in all_stocks:
        cur = conn.execute(
            "SELECT 1 FROM kline_cache WHERE symbol=? AND period='daily' AND trade_date IN ('{}') LIMIT 1".format(
                "','".join(sorted(MISSING_DATES))),
            (stock,)
        )
        if cur.fetchone() is None:
            needs.append(stock)
    print(f"需补齐: {len(needs)} 只")
    return needs

def get_daily_from_sina(code):
    """从新浪获取最近10个交易日日线"""
    url = f"https://quotes.sina.com.cn/usstock/cn/api/jsonp_v2.php/var%20_{code}=/US_MinKService.getDailyK?symbol={code}"
    try:
        # 直接用新浪日K线API
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen=10"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        result = {}
        for item in data:
            date = item.get('day') or item.get('date', '')
            result[date] = {
                'open': float(item['open']),
                'high': float(item['high']),
                'low': float(item['low']),
                'close': float(item['close']),
                'volume': float(item['volume']),
            }
        return result
    except Exception as e:
        return None


# 腾讯行情API - 比新浪更稳定
def get_daily_from_tencent(symbol):
    """从腾讯获取日线（最近5个交易日）"""
    # 腾讯的日K线API
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,10,qfq"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('code') != 0:
            return None
        # 提取日线数据
        kdata = data.get('data', {})
        stock_data = kdata.get(symbol, {})
        days = stock_data.get('day', stock_data.get('qfqday', stock_data.get('hfqday', [])))
        if not days:
            return None
        result = {}
        for item in days:
            date = item[0]
            result[date] = {
                'open': float(item[1]),
                'close': float(item[2]),
                'high': float(item[3]),
                'low': float(item[4]),
                'volume': float(item[5]) if len(item) > 5 else 0,
            }
        return result
    except Exception:
        return None


def main():
    conn = sqlite3.connect(DB_PATH)
    missing = get_missing_stocks(conn)
    if not missing:
        print("无需补齐")
        return

    ok, fail = 0, 0
    batch = []
    BATCH_SQL = 500
    
    for i, bare_code in enumerate(missing):
        # 构建腾讯格式：sh000001 / sz002057
        if bare_code.startswith('6') or bare_code.startswith('688'):
            tenc = f"sh{bare_code}"
        elif bare_code.startswith('8') or bare_code.startswith('4'):
            tenc = f"bj{bare_code}"
        else:
            tenc = f"sz{bare_code}"

        data = get_daily_from_tencent(tenc)
        if data is None:
            fail += 1
            if (i + 1) % 500 == 0:
                print(f"  [{i+1}/{len(missing)}] ok={ok} fail={fail}")
            continue

        for date, k in data.items():
            if date not in MISSING_DATES:
                continue
            batch.append((
                bare_code, 'tencent', 'daily', date,
                k['open'], k['close'], k['high'], k['low'],
                k['volume'], 0.0
            ))

        ok += 1

        if len(batch) >= BATCH_SQL:
            conn.executemany(
                "INSERT OR REPLACE INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch
            )
            conn.commit()
            batch = []

        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(missing)}] ok={ok} fail={fail}")

        if (i + 1) % 20 == 0:
            time.sleep(0.06)  # 控制频率

    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO kline_cache "
            "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch
        )
        conn.commit()

    conn.close()
    print(f"\n完成: 成功={ok}, 失败={fail}")

if __name__ == '__main__':
    main()
