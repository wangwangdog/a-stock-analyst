#!/usr/bin/env python3
"""
涨停洗盘策略复盘脚本
每天收盘后检查昨日涨停洗盘策略选出的 4 只股票今日涨跌情况
"""

import sqlite3
import requests
from datetime import datetime, timedelta
import sys

# 配置
DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
STRATEGY_ID = "limit_up_shakeout"

# 东方财富 API 获取实时价格
# secid: 1=sh, 0=sz, 2=bj
# fields2=f51 (最新价)
def get_realtime_price(symbol: str) -> dict:
    """获取股票实时价格"""
    try:
        # 判断市场
        if symbol.startswith('6'):
            market = '1'  # 上海
        elif symbol.startswith(('0', '3')):
            market = '0'  # 深圳
        else:
            market = '2'  # 北京
        
        url = f"http://push2his.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&fields1=f1,f3&fields2=f51"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if data.get('data'):
            return {
                'price': float(data['data']['f51']),
                'change': float(data['data'].get('f44', 0)),
                'change_pct': float(data['data'].get('f43', 0))
            }
    except Exception as e:
        print(f"获取 {symbol} 价格失败：{e}")
    return None

def get_yesterday_stocks() -> list:
    """获取昨日涨停洗盘策略选出的 4 只股票"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 获取昨天日期（自动处理周末）
        cursor.execute("""
            SELECT MAX(date) FROM strategy_picks 
            WHERE strategy = ? 
            AND date < date('now')
        """, (STRATEGY_ID,))
        
        result = cursor.fetchone()
        if not result or not result[0]:
            print("未找到昨日涨停洗盘策略选股数据")
            conn.close()
            return []
        
        select_date = result[0]
        
        # 获取当日 4 只股票
        cursor.execute("""
            SELECT symbol FROM strategy_picks 
            WHERE strategy = ? AND date = ?
            ORDER BY rank 
            LIMIT 4
        """, (STRATEGY_ID, select_date))
        
        stocks = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        print(f"查询到 {select_date} 涨停洗盘策略选股：{stocks}")
        return stocks
    except Exception as e:
        print(f"查询数据库失败：{e}")
        return []

def get_stock_names(symbols: list) -> dict:
    """获取股票名称"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        names = {}
        for symbol in symbols:
            cursor.execute("SELECT name FROM all_stock_info WHERE symbol = ?", (symbol,))
            result = cursor.fetchone()
            if result:
                names[symbol] = result[0]
            else:
                names[symbol] = symbol
        conn.close()
        return names
    except Exception as e:
        print(f"获取股票名称失败：{e}")
        return {s: s for s in symbols}

def main():
    # 1. 获取昨日选出的股票
    stocks = get_yesterday_stocks()
    if not stocks:
        return
    
    stock_names = get_stock_names(stocks)
    
    # 2. 获取今日收盘价（或最新价）
    results = []
    for symbol in stocks:
        price_info = get_realtime_price(symbol)
        if price_info:
            name = stock_names.get(symbol, symbol)
            results.append({
                'symbol': symbol,
                'name': name,
                'price': price_info['price'],
                'change': price_info['change'],
                'change_pct': price_info['change_pct']
            })
    
    # 3. 生成报告
    if not results:
        print("未能获取到股票价格数据")
        return
    
    print(f"\n📊 【涨停洗盘策略复盘】")
    print(f"选股日期：{datetime.now().strftime('%Y-%m-%d')}")
    print(f"\n{'代码':<10}{'名称':<10}{'最新价':<10}{'涨跌':<10}{'涨跌幅':<10}")
    print("-" * 50)
    
    up_count = 0
    down_count = 0
    
    for r in results:
        change_str = f"{r['change']:+.2f}"
        pct_str = f"{r['change_pct']:+.2f}%"
        marker = "📈" if r['change'] > 0 else "📉" if r['change'] < 0 else "➡️"
        
        if r['change'] > 0:
            up_count += 1
        elif r['change'] < 0:
            down_count += 1
        
        print(f"{r['symbol']:<10}{r['name']:<10}{r['price']:<10.2f}{change_str:<10}{pct_str:<10} {marker}")
    
    print("-" * 50)
    print(f"上涨：{up_count}只 | 下跌：{down_count}只 | 持平：{len(results) - up_count - down_count}只")
    
    # 4. 发送飞书消息
    try:
        import json
        
        text = f"【涨停洗盘策略复盘】\n"
        text += f"选股日期：{datetime.now().strftime('%Y-%m-%d')}\n\n"
        text += "📊 复盘结果：\n"
        
        for r in results:
            change_str = f"{r['change']:+.2f}"
            pct_str = f"{r['change_pct']:+.2f}%"
            marker = "📈" if r['change'] > 0 else "📉" if r['change'] < 0 else "➡️"
            text += f"• {r['name']}({r['symbol']}): {r['price']:.2f}元 {change_str} ({pct_str}) {marker}\n"
        
        text += f"\n📊 统计：涨{up_count}跌{down_count}"
        
        # 飞书 API
        webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook_token_here"
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        # requests.post(webhook_url, json=payload, timeout=5)
        # 注释掉，避免 webhook 配置问题
        
    except Exception as e:
        print(f"发送飞书消息失败：{e}")

if __name__ == "__main__":
    main()
