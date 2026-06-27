"""
盘口异动增量采集器

采集东方财富23类盘口异动数据，写入 market_anomaly + stock_records 表。
可在盘中每5分钟通过 cron 定时采集。

用法:
    python market_anomaly_collector.py              # 采集一次全量异动
    python market_anomaly_collector.py --watch       # 仅采关注池相关异动
"""
import sys
import os
import logging
import sqlite3
import re
import time
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger('anomaly_collector')

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent  # a_stock_backend/
sys.path.insert(0, str(BACKEND_DIR))


def _is_trading_day() -> bool:
    """通过交易日历判断今日是否为交易日"""
    try:
        conn = _get_conn()
        today = date.today().strftime("%Y-%m-%d")
        r = conn.execute("SELECT 1 FROM trade_calendar WHERE cal_date=? AND is_open=1", (today,)).fetchone()
        conn.close()
        return r is not None
    except Exception:
        return True  # 无法判断时默认 True


def _get_conn():
    return sqlite3.connect(DB_PATH)


def _parse_anomaly_info(info_str) -> tuple:
    """解析盘口异动的相关信息字段，提取价格和成交量

    东方财富异动数据的"相关信息"格式因类型而异，常见格式：
    - 大单类: "375400,5.11000,-0.030476,1918294"   (数量,单价,涨跌幅,金额)
    - 涨跌停: "7.480000,60300,7.48000,0.050562"    (价格,数量,价格,涨跌幅)
    - 走势类: "0.099458,95.40000,0.099458"          (涨跌幅,价格,涨跌幅)
    - 新高类: "3.700000,3.69000,0.072674"           (...)

    启发式策略：
    - 价格: 0.1~10000 范围内的浮点数（大概率是股价或指数）
    - 数量: 绝对值 > 1000 的整数（大概率是成交量股数）
    - 涨跌幅: -1~1 之间的小数（排除）
    """
    raw = str(info_str or "")
    if not raw or raw == "nan":
        return 0.0, 0

    # 提取所有数字
    nums = []
    for part in re.split(r'[,，\s]+', raw.strip()):
        part = part.strip()
        if not part:
            continue
        try:
            val = float(part)
            nums.append(val)
        except ValueError:
            continue

    if not nums:
        return 0.0, 0

    price = 0.0
    vol = 0

    # 找成交量（>1000 的整数或接近整数的大数）
    for v in nums:
        if abs(v) >= 1000 and abs(v - round(v)) < 0.01:
            vol = int(abs(v))
            break
    if vol == 0:
        # 没找到大数，取绝对值最大的
        nums_sorted = sorted(nums, key=abs, reverse=True)
        for v in nums_sorted:
            if abs(v) >= 100:
                vol = int(abs(v))
                break

    # 找价格：在 0.1~10000 之间且不是数量
    for v in nums:
        if 0.1 <= abs(v) <= 10000:
            if vol > 0 and abs(abs(v) - vol) < 0.01:
                continue  # 价格和数量相同，跳过
            if abs(v) > 1:  # 排除涨跌幅（小数）
                price = abs(v)
                break

    # fallback: 如果还没找到价格，取第一个 > 0.1 的值
    if price == 0.0:
        for v in nums:
            if 0.1 <= abs(v) <= 10000 and abs(v) != vol:
                price = abs(v)
                break

    return round(price, 4), vol


# ============================================================
# 2. 盘口异动采集
# ============================================================




# — 异动类型定义（与 monitor/__init__.py 一致）
ALL_ANOMALY_TYPES = [
    '大笔买入', '大笔卖出',           # 大单异动
    '火箭发射', '高台跳水',           # 走势异动
    '快速反弹', '加速下跌',           # 涨跌异动
    '封涨停板', '打开涨停板',          # 涨停相关
    '封跌停板', '打开跌停板',          # 跌停相关
    '有大买盘', '有大卖盘',           # 盘口压力
    '竞价上涨', '竞价下跌',           # 竞价异动
    '高开5日线', '低开5日线',         # 均线缺口
    '向上缺口', '向下缺口',           # 缺口异动
    '60日新高', '60日新低',           # 新高新低
    '60日大幅上涨', '60日大幅下跌',
]

# 英文key映射（中文 → 英文key）
ANOMALY_KEYS = {
    '大笔买入': 'large_buy', '大笔卖出': 'large_sell',
    '火箭发射': 'rocket', '高台跳水': 'cliff_dive',
    '快速反弹': 'rapid_bounce', '加速下跌': 'accelerate_drop',
    '封涨停板': 'limit_up', '打开涨停板': 'limit_up_break',
    '封跌停板': 'limit_down', '打开跌停板': 'limit_down_break',
    '有大买盘': 'big_buy_pressure', '有大卖盘': 'big_sell_pressure',
    '竞价上涨': 'auction_up', '竞价下跌': 'auction_down',
    '高开5日线': 'gap_above_ma5', '低开5日线': 'gap_below_ma5',
    '向上缺口': 'gap_up', '向下缺口': 'gap_down',
    '60日新高': 'high_60d', '60日新低': 'low_60d',
    '60日大幅上涨': 'big_up_60d', '60日大幅下跌': 'big_down_60d',
}


def collect_anomaly(watch_only: bool = False) -> dict:
    """采集盘口异动并写入 market_anomaly + stock_records 表

    Args:
        watch_only: 仅采关注池相关异动（优化速度）

    Returns:
        {"types_collected": N, "records_written": N, "errors": [...]}
    """
    try:
        from monitor import get_monitor
    except ImportError:
        logger.error("monitor 模块导入失败，尝试直接导入")
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from monitor import get_monitor
        except ImportError:
            logger.error("monitor 模块不可用，请确保路径正确")
            return {"types_collected": 0, "records_written": 0, "errors": ["monitor import failed"]}

    # 获取关注池（仅为了 watch_only 模式过滤）
    watch_symbols = set()
    if watch_only:
        conn = _get_conn()
        try:
            for (sym,) in conn.execute("SELECT symbol FROM favorites LIMIT 50"):
                watch_symbols.add(str(sym).strip())
            for (sym,) in conn.execute("SELECT DISTINCT symbol FROM strategy_picks ORDER BY date DESC LIMIT 50"):
                watch_symbols.add(str(sym).strip())
            for (sym,) in conn.execute("SELECT symbol FROM zt_pool WHERE date=(SELECT MAX(date) FROM zt_pool) LIMIT 100"):
                watch_symbols.add(str(sym).strip())
        except Exception:
            pass
        conn.close()

    mon = get_monitor()
    today = date.today().strftime("%Y-%m-%d")
    errors = []
    all_records = []

    for cn_name in ALL_ANOMALY_TYPES:
        try:
            items = mon.get_changes(cn_name, top_n=100)
        except Exception as e:
            err = f"{cn_name}: {e}"
            logger.warning(err)
            errors.append(err)
            continue

        if not items:
            continue

        anomaly_key = ANOMALY_KEYS.get(cn_name, cn_name)
        for item in items:
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            occur_time = str(item.get("time", "")).strip()

            # 价格/数量从 "相关信息" 字段解析（格式因异动类型而异）
            # 启发式：找0.1~1000的值作为价格，>1000的作为成交量
            price, vol = _parse_anomaly_info(item.get("相关信息", ""))

            # watch_only 过滤：不在关注池内的跳过
            if watch_only and watch_symbols:
                pure_code = code.lstrip("0") if code else ""
                matched = False
                for ws in watch_symbols:
                    if ws == code or ws.lstrip("0") == pure_code or ws.endswith(code):
                        matched = True
                        break
                if not matched:
                    continue

            all_records.append({
                "symbol": code,
                "name": name,
                "anomaly_type": anomaly_key,
                "anomaly_cn": cn_name,
                "occur_time": occur_time,
                "price": price,
                "volume": vol,
                "extra": f"{{\"cn_name\":\"{cn_name}\",\"name\":\"{name}\"}}",
            })

    if not all_records:
        logger.info("本次无盘口异动记录")
        return {"types_collected": len(ALL_ANOMALY_TYPES), "records_written": 0, "errors": errors}

    # 写入数据库
    conn = _get_conn()
    try:
        written = 0
        for r in all_records:
            conn.execute(
                """INSERT OR IGNORE INTO market_anomaly
                   (symbol, anomaly_type, occur_time, price, volume, extra)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (r["symbol"], r["anomaly_type"], r["occur_time"],
                 r["price"], r["volume"], r["extra"]),
            )
            written += 1

        # 同时写入 stock_records（兼容旧管道）
        for r in all_records:
            conn.execute(
                """INSERT INTO stock_records
                   (股票代码, 股票名称, 买入数量, 单价, 涨跌幅, 金额, 买入时间, 买入日期)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["symbol"], r["name"], r["volume"], r["price"],
                 0.0, r["volume"] * r["price"],
                 r["occur_time"], today),
            )
        conn.commit()
        logger.info(f"✅ 写入 market_anomaly {written} 条 + stock_records {written} 条")
    except Exception as e:
        logger.error(f"写入数据库失败: {e}")
        conn.rollback()
        errors.append(str(e))
    finally:
        conn.close()

    return {
        "types_collected": len(ALL_ANOMALY_TYPES),
        "records_written": len(all_records),
        "errors": errors,
    }


# ===== 命令行入口 =====
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    watch_only = "--watch" in sys.argv
    result = collect_anomaly(watch_only=watch_only)
    print(f"类型采集: {result['types_collected']}")
    print(f"记录写入: {result['records_written']}")
    if result["errors"]:
        print(f"错误: {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"  ⚠ {e}")
