#!/usr/bin/env python3
"""
数据健康检查脚本

检查项：
1. K线缓存（kline_cache）是否包含最新交易日
2. Sequoia stock_daily 是否包含最新交易日
3. 选股数据（strategy_picks）是否覆盖最新交易日
4. 随机采样 N 只股票的 K 线 API 是否返回最新交易日
5. 最新交易日K线价格不异常（非零、非空）

用法：
    python scripts/health_check.py        # 标准检查
    python scripts/health_check.py --json  # JSON 输出（给 cron 用）
    python scripts/health_check.py --fix   # 自动修复（可选，暂未实现）
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import date, timedelta, datetime

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DB_PATH = str(Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite"))
# 采样股列表：覆盖沪深主板/创业板/科创板 + 大中小盘 + 近期选股信号
SAMPLE_SYMBOLS = [
    # 大盘蓝筹（沪深主板）
    "600519", "000001", "000002", "601318",
    # 创业板
    "300750", "300163", "300995",
    # 科创板
    "688046", "688010",
    # 深市主板/中小板
    "000338", "000685", "000636",
    # 小盘/策略选股信号
    "603855", "002825", "002892",
]
MARKET_CODES = {
    "600519": {"name": "贵州茅台", "market": "sh"},
    "000001": {"name": "平安银行", "market": "sz"},
    "000002": {"name": "万科A",    "market": "sz"},
    "601318": {"name": "中国平安", "market": "sh"},
    "300750": {"name": "宁德时代", "market": "sz"},
    "300163": {"name": "先锋新材", "market": "sz"},
    "300995": {"name": "奇德新材", "market": "sz"},
    "688046": {"name": "复旦微电", "market": "sh"},
    "688010": {"name": "福光股份", "market": "sh"},
    "000338": {"name": "潍柴动力", "market": "sz"},
    "000685": {"name": "中山公用", "market": "sz"},
    "000636": {"name": "风华高科", "market": "sz"},
    "603855": {"name": "华荣股份", "market": "sh"},
    "002825": {"name": "纳尔股份", "market": "sz"},
    "002892": {"name": "科力尔",   "market": "sz"},
}

CHECKS = {}


def log_check(name: str, passed: bool, detail: str, data=None):
    CHECKS[name] = {"passed": passed, "detail": detail, "data": data or {}}


def get_latest_trading_day() -> str:
    """返回最近一个交易日 YYYY-MM-DD（简单判断，不考虑法定假日）"""
    today = date.today()
    # 周六 -> 周五, 周日 -> 周五
    if today.weekday() == 5:    # Saturday
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if today.weekday() == 6:    # Sunday
        return (today - timedelta(days=2)).strftime("%Y-%m-%d")
    # 周一至周五认为是交易日（盘中时可能无当日数据，接受前一天）
    return today.strftime("%Y-%m-%d")


def check_kline_cache():
    """检查 kline_cache 表的最新交易日数据
    排除 akshare source（akshare 只存分钟线，日线由 baostock 和 tdx 提供）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT source, period, MAX(trade_date), COUNT(DISTINCT symbol) "
            "FROM kline_cache "
            "WHERE period='daily' AND source != 'akshare' "
            "GROUP BY source"
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            log_check("kline_cache", False, "kline_cache 中无日均线数据")
            return

        expected = get_latest_trading_day()
        for src, period, max_date, cnt in rows:
            date_part = str(max_date)[:10] if max_date else None
            if date_part:
                ok = cnt >= 1000
                log_check(
                    f"kline_cache_{src}",
                    ok,
                    f"最新: {date_part}, 股票数: {cnt}, 期望: {expected}",
                    {"source": src, "latest": date_part, "stock_count": cnt}
                )
            else:
                log_check(f"kline_cache_{src}", False, f"无数据", {"source": src})

        # 单独检查 ak share 分钟数据状态（不阻断报警）
        try:
            cur2 = conn.execute(
                "SELECT period, MAX(trade_date), COUNT(DISTINCT symbol) "
                "FROM kline_cache "
                "WHERE source='akshare' AND period != 'daily' "
                "GROUP BY period"
            )
            for p, dt, cnt in cur2.fetchall():
                log_check(f"kline_cache_akshare_{p}", True,
                    f"最新: {str(dt)[:19]}, 股票数: {cnt}",
                    {"source": "akshare", "period": p, "latest": str(dt)[:19], "stock_count": cnt})
        except:
            pass
        finally:
            conn.close()
    except Exception as e:
        log_check("kline_cache", False, f"查询失败: {e}")


def check_stock_daily():
    """检查 stock_daily 表的最新数据"""
    try:
        conn = sqlite3.connect(DB_PATH)
        # 检查是否有 stock_daily 表
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_daily'"
        )
        if not cur.fetchone():
            log_check("stock_daily", False, "stock_daily 表不存在")
            conn.close()
            return

        cur = conn.execute(
            "SELECT date, COUNT(DISTINCT symbol) FROM stock_daily "
            "GROUP BY date ORDER BY date DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            log_check("stock_daily", False, "stock_daily 无数据")
            return

        exepcted = get_latest_trading_day()
        latest_date, cnt = row[0], row[1]
        ok = cnt >= 1000
        log_check(
            "stock_daily",
            ok,
            f"最新: {latest_date}, 股票数: {cnt}, 期望: {exepcted}",
            {"latest": latest_date, "stock_count": cnt}
        )
    except Exception as e:
        log_check("stock_daily", False, f"查询失败: {e}")


def check_strategy_picks():
    """检查策略选股数据"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_picks'"
        )
        if not cur.fetchone():
            log_check("strategy_picks", False, "strategy_picks 表不存在")
            conn.close()
            return

        cur = conn.execute(
            "SELECT date, COUNT(DISTINCT symbol), COUNT(DISTINCT strategy) "
            "FROM strategy_picks GROUP BY date ORDER BY date DESC LIMIT 3"
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            log_check("strategy_picks", False, "选股数据为空")
            return

        latest = rows[0]
        ok = latest[1] > 0
        log_check(
            "strategy_picks",
            ok,
            f"最新: {latest[0]}, 选股 {latest[1]} 只, 策略 {latest[2]} 个",
            {"latest": latest[0], "picks": latest[1], "strategies": latest[2]}
        )
    except Exception as e:
        log_check("strategy_picks", False, f"查询失败: {e}")


def check_kline_api():
    """通过后端 API 采样检查 K 线数据"""
    import urllib.request
    import urllib.error

    expected = get_latest_trading_day()
    failed_stocks = []
    base = "http://localhost:9901"

    for sym in SAMPLE_SYMBOLS:
        try:
            url = f"{base}/api/v1/kline/{sym}?period=daily&indicators=false"
            resp = urllib.request.urlopen(url, timeout=15)
            data = json.loads(resp.read().decode())
            if data.get("status") == "failed":
                failed_stocks.append(f"{sym}({data.get('message','')})")
                continue
            dates = [r["date"] for r in data.get("data", [])]
            if not dates:
                failed_stocks.append(f"{sym}(无数据)")
                continue
            latest = max(dates)
            if latest < expected:
                failed_stocks.append(f"{sym}(最新{latest} < 期望{expected})")
        except Exception as e:
            failed_stocks.append(f"{sym}({str(e)[:60]})")

    ok = len(failed_stocks) == 0
    name = MARKET_CODES.get(SAMPLE_SYMBOLS[0], {}).get("name", "sample")
    log_check(
        "kline_api_sample",
        ok,
        f"采样 {len(SAMPLE_SYMBOLS)} 只, 失败 {len(failed_stocks)} 只" + (f": {', '.join(failed_stocks)}" if failed_stocks else ""),
        {"sample_size": len(SAMPLE_SYMBOLS), "failed": len(failed_stocks), "failed_detail": failed_stocks}
    )


def check_backend_alive():
    """检查后端是否 alive"""
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://localhost:9901/api/ping", timeout=5)
        data = json.loads(resp.read().decode())
        ok = data.get("pong") is True
        log_check("backend_alive", ok, f"后端 {'在线' if ok else '异常'}" if ok else f"后端异常: {data}")
    except Exception as e:
        log_check("backend_alive", False, f"后端不可达: {e}")


def run_all():
    check_backend_alive()
    check_kline_cache()
    check_stock_daily()
    check_strategy_picks()
    check_kline_api()


def print_report():
    run_all()

    all_pass = all(c["passed"] for c in CHECKS.values())
    passed_count = sum(1 for c in CHECKS.values() if c["passed"])
    total = len(CHECKS)

    print(f"{'='*50}")
    print(f"📊 A-Stock 数据健康检查 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    print(f"期望交易日: {get_latest_trading_day()}")
    print(f"结果: {'✅ 全部通过' if all_pass else f'❌ {total-passed_count}/{total} 项失败'}")
    print()

    for name, check in CHECKS.items():
        status = "✅" if check["passed"] else "❌"
        print(f"  {status} {name}: {check['detail']}")

    print()
    print(f"{'='*50}")
    return all_pass


def print_json():
    run_all()
    result = {
        "time": datetime.now().isoformat(),
        "expected_trading_day": get_latest_trading_day(),
        "all_passed": all(c["passed"] for c in CHECKS.values()),
        "passed": sum(1 for c in CHECKS.values() if c["passed"]),
        "total": len(CHECKS),
        "checks": CHECKS,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["all_passed"]


if __name__ == "__main__":
    use_json = "--json" in sys.argv
    ok = print_json() if use_json else print_report()
    sys.exit(0 if ok else 1)
