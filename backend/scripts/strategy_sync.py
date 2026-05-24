"""
Sequoia-X 策略自动同步
在行情更新 + 盘口数据 + 大单数据都就绪后执行策略选股。

检查前置条件（当天数据是否存在），数据到位后才跑策略。
"""
import sys
import os
import argparse
from datetime import date
from pathlib import Path

# 添加 backend 目录到 path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from data.sequoia_engine import daily_sync, check_status, DB_PATH


def data_ready() -> tuple[bool, str]:
    """检查当天前置数据是否就绪"""
    import sqlite3
    today = date.today().strftime("%Y-%m-%d")
    
    if not os.path.exists(DB_PATH):
        return False, "数据库文件不存在"
    
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 检查 stock_daily 是否有今日数据
        r = conn.execute(
            "SELECT 1 FROM stock_daily WHERE date=? LIMIT 1", (today,)
        ).fetchone()
        if not r:
            return False, f"stock_daily 缺少 {today} 数据"
        
        # 2. 检查 hzeveryday 是否有今日数据（盘口数据）
        r2 = conn.execute(
            "SELECT 1 FROM hzeveryday WHERE 买入日期=? LIMIT 1", (today,)
        ).fetchone()
        if not r2:
            return False, f"hzeveryday 缺少 {today} 数据"
        
        # 3. 检查 big_deal_summary 是否有今日数据（软检查）
        r3 = conn.execute(
            "SELECT 1 FROM big_deal_summary WHERE trade_date=? LIMIT 1", (today,)
        ).fetchone()
        # 不作为硬要求
        
        return True, "数据就绪"
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Sequoia-X 策略自动同步")
    parser.add_argument("--force", action="store_true", help="强制运行，跳过数据就绪检查")
    parser.add_argument("--max-retries", type=int, default=0, help="数据未就绪时的最大重试次数")
    parser.add_argument("--retry-interval", type=int, default=300, help="重试间隔（秒）")
    args = parser.parse_args()
    
    print(f"📅 {date.today()} Sequoia-X 策略自动同步")
    
    if not args.force:
        ready, msg = data_ready()
        if not ready:
            print(f"⏸️ 前置数据未就绪: {msg}")
            print("跳过本次执行，等待下次 cron 触发")
            sys.exit(0)
        print(f"✅ 前置数据检查通过")
    else:
        print("⚡ 强制模式，跳过数据检查")
    
    print("🔄 开始 Sequoia-X 策略同步...")
    try:
        result = daily_sync()
        if result:
            status = check_status()
            picks_today = status.get("picks_today", 0)
            print(f"✅ 策略同步完成！今日选股: {picks_today} 只")
            print(f"   同步数据: {result.get('sync_count', 0)} 条")
            print(f"   总选股: {result.get('total_picks', 0)} 只")
        else:
            print("✅ 策略同步完成")
    except Exception as e:
        print(f"❌ 策略同步失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
