#!/usr/bin/env python3
"""
每日数据同步脚本（已集成到 a-stock-analyst 项目内）

用法：
    python daily_sync.py                  # 日常同步（同步+选股）
    python daily_sync.py --backfill       # 全市场历史回填（首次用）
    python daily_sync.py --no-strategy    # 只同步，不跑策略
    python daily_sync.py --status         # 查看状态
"""

import sys
import argparse
from pathlib import Path

# 只需要将 backend/ 加入路径
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

STRATEGY_LABELS = {
    "ma_volume": "均线放量", "turtle_trade": "海龟交易",
    "high_tight_flag": "高窄旗形", "limit_up_shakeout": "涨停洗盘",
    "uptrend_limit_down": "跌停反包", "rps_breakout": "RPS突破",
}


def cmd_status():
    from data.sequoia_engine import check_status
    s = check_status()
    print(f"数据库: {'✅ 就绪' if s['db_exists'] else '❌ 未初始化'}")
    print(f"股票数: {s['stock_count']}")
    print(f"最新日: {s['latest_date']}")
    print(f"今日选股: {s['picks_today']} 只")


def cmd_backfill():
    print("📥 全市场历史回填（约 12 分钟，请耐心等待）...")
    from data.sequoia_engine import DB_PATH
    from sequoia_x.core.config import Settings
    from sequoia_x.data.engine import DataEngine

    settings = Settings(db_path=DB_PATH, start_date="2024-01-01", feishu_webhook_url="http://localhost/unused")
    engine = DataEngine(settings)
    all_symbols = engine.get_all_symbols()
    engine.backfill(all_symbols)

    from data.sequoia_engine import check_status
    s = check_status()
    print(f"✅ 回填完成: {s['stock_count']} 只股票, 最新日: {s['latest_date']}")


def cmd_sync_only():
    print("📦 仅数据同步...")
    from data.sequoia_engine import DB_PATH
    from sequoia_x.core.config import Settings
    from sequoia_x.data.engine import DataEngine

    settings = Settings(db_path=DB_PATH, start_date="2024-01-01", feishu_webhook_url="http://localhost/unused")
    engine = DataEngine(settings)
    count = engine.sync_today_bulk()
    print(f"✅ 同步完成: 写入 {count} 条数据")


def cmd_daily():
    """完整日常同步"""
    print("🔄 Sequoia-X 日常同步 + 选股...")
    from data.sequoia_engine import daily_sync

    result = daily_sync()
    if result["status"] == "ok":
        print(f"✅ 同步完成")
        print(f"   增量写入: {result['sync_count']} 条")
        print(f"   当前股票: {result['total_symbols']} 只")
        print(f"   策略选股: {result['total_picks']} 只")
        print(f"   日期: {result['date']}")
        for key, cnt in result["picks"].items():
            print(f"     {STRATEGY_LABELS.get(key, key)}: {cnt} 只")
    else:
        print(f"❌ 同步失败: {result.get('error', '未知错误')}")
        sys.exit(1)


def _check_trading_day() -> bool:
    """通过 TradingCalendar 判断今天是不是交易日，非交易日直接退出。

    使用 merged DB 的 trade_calendar 表（无需外部网络）。
    仅在 merged DB 不可用时回退到 heuristic 规则。
    """
    from pathlib import Path
    from datetime import date
    import importlib.util
    try:
        _BASE_DIR = Path(__file__).resolve().parent.parent.parent / "src"
        spec = importlib.util.spec_from_file_location(
            "trading_calendar",
            str(_BASE_DIR / "chanlun" / "utils" / "trading_calendar.py"),
        )
        tc_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tc_mod)
        cal = tc_mod.get_calendar()
        today_str = date.today().strftime("%Y-%m-%d")
        is_trading = cal.is_trading_day(today_str)
        if not is_trading:
            print(f"📅 {today_str} 非交易日，跳过本次同步")
        return is_trading
    except Exception as e:
        print(f"⚠ 交易日历模块加载失败: {e}，默认按交易日处理")
        return True


def main():
    # 定时任务入口：判断今天是否交易日，非交易日直接退出
    if not _check_trading_day():
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Sequoia-X 日常数据同步与选股")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--no-strategy", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    try:
        if args.status:
            cmd_status()
        elif args.backfill:
            cmd_backfill()
        elif args.no_strategy:
            cmd_sync_only()
        else:
            cmd_daily()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
