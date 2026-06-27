#!/usr/bin/env python3
"""
交易日历种子脚本

向 merged DB 的 trade_calendar 表写入交易日数据。
仅在缺少年份的数据时补充（不会覆盖已有的年份）。

数据来源：硬编码的已知节假日 + 周末规则。
如需精确数据，可从交易所官方获取并更新此表。

用法：
    python scripts/seed_trade_calendar.py          # 补充缺失年份
    python scripts/seed_trade_calendar.py --force   # 强制覆盖已有数据
    python scripts/seed_trade_calendar.py --status  # 查看状态
"""

import sys
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"

# 已知 A 股非交易日（法定节假日 + 调休日）
# 格式：{年份: {(月, 日), ...}}
# 周末自动处理，这里只列工作日休市的日子
PUBLIC_HOLIDAYS = {
    2024: {
        (1, 1),   # 元旦
        (2, 9), (2, 10), (2, 11), (2, 12), (2, 13), (2, 14), (2, 15), (2, 16), (2, 17),  # 春节
        (2, 18),
        (4, 4), (4, 5), (4, 6),   # 清明节
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),  # 劳动节
        (6, 10),  # 端午节
        (9, 15), (9, 16), (9, 17),  # 中秋节
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7),  # 国庆
    },
    2025: {
        (1, 1),
        (1, 28), (1, 29), (1, 30), (1, 31),
        (2, 1), (2, 2), (2, 3), (2, 4),
        (4, 4), (4, 5), (4, 6),
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
        (5, 31), (6, 1), (6, 2),
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7), (10, 8),
    },
    2026: {
        (1, 1),
        (2, 16), (2, 17), (2, 18), (2, 19), (2, 20), (2, 21), (2, 22),
        (2, 23), (2, 24),
        (4, 4), (4, 5), (4, 6),
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
        (6, 19), (6, 20), (6, 21),
        (9, 26), (9, 27), (9, 28),
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7),
    },
}

# 调休上班的周末（即本该休但变工作日的日子）
# 格式: {年份: {(月, 日), ...}}
EXTRA_WORKDAYS = {
    2024: {
        (2, 4),   # 周日 → 工作日（春节调休）
        (2, 18),  # 周日 → 工作日
        (4, 7),   # 周日 → 工作日
        (4, 28),  # 周日 → 工作日
        (5, 11),  # 周六 → 工作日
        (9, 14),  # 周六 → 工作日
        (9, 29),  # 周日 → 工作日
        (10, 12),  # 周六 → 工作日
    },
    2025: {
        (1, 26),  # 周日 → 工作日
        (2, 8),   # 周六 → 工作日
        (4, 27),  # 周日 → 工作日
        (9, 28),  # 周日 → 工作日
        (10, 11),  # 周六 → 工作日
    },
    2026: {
        (2, 15),  # 周日 → 工作日
        (2, 28),  # 周六 → 工作日
        (4, 5),   # 周日 → 工作日
        (5, 9),   # 周六 → 劳动节调休
        (9, 27),  # 周日 → 国庆调休
        (10, 10),  # 周六 → 工作日
    },
}


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _get_default_holidays_for_year(year: int) -> set:
    """生成指定年份的已知节假日"""
    current_holidays = PUBLIC_HOLIDAYS.get(year, set())
    extra_wds = EXTRA_WORKDAYS.get(year, set())
    holidays = set()

    start = date(year, 1, 1)
    end = date(year, 12, 31)
    cur = start
    while cur <= end:
        if (cur.month, cur.day) in current_holidays:
            holidays.add(cur)
        cur += timedelta(days=1)

    return holidays, extra_wds


def generate_year(year: int) -> list:
    """生成指定年份的交易日历"""
    holidays, extra_wds = _get_default_holidays_for_year(year)

    records = []
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    cur = start
    while cur <= end:
        is_holiday = (cur.month, cur.day) in {(h.month, h.day) for h in holidays}
        is_weekend = _is_weekend(cur)
        is_extra = (cur.month, cur.day) in extra_wds

        if is_extra:
            is_trading = True
        elif is_holiday:
            is_trading = False
        elif is_weekend:
            is_trading = False
        else:
            is_trading = True

        records.append((cur.isoformat(), 1 if is_trading else 0))
        cur += timedelta(days=1)

    return records


def get_existing_years(conn) -> set:
    """查询 DB 已有的年份"""
    cur = conn.execute("SELECT DISTINCT SUBSTR(calendar_date,1,4) FROM trade_calendar")
    return {int(r[0]) for r in cur.fetchall() if r[0]}


def seed(force: bool = False):
    """补充交易日历数据"""
    conn = sqlite3.connect(str(DB_PATH))

    # 确保表存在
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_calendar (
            calendar_date TEXT PRIMARY KEY,
            is_trading_day INTEGER NOT NULL
        )
    """)

    existing_years = get_existing_years(conn)
    current_year = date.today().year

    # 要处理的年份：当前年 + 前后3年
    target_years = set(range(current_year - 1, current_year + 3))

    if not force:
        target_years = target_years - existing_years

    if not target_years:
        print("所有目标年份已有数据，无需更新")
        conn.close()
        return

    total_inserted = 0
    for yr in sorted(target_years):
        records = generate_year(yr)
        inserted = 0
        for cal_date, is_trading in records:
            try:
                if force:
                    conn.execute(
                        "INSERT OR REPLACE INTO trade_calendar (calendar_date, is_trading_day) VALUES (?, ?)",
                        (cal_date, is_trading)
                    )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO trade_calendar (calendar_date, is_trading_day) VALUES (?, ?)",
                        (cal_date, is_trading)
                    )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        total_inserted += inserted
        print(f"  {yr}: 写入 {inserted} 条（交易日历）")

    conn.close()
    print(f"\n✅ 完成，共写入 {total_inserted} 条记录")

    # 状态摘要
    show_status()


def show_status():
    """显示交易日历状态"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT MIN(calendar_date), MAX(calendar_date) FROM trade_calendar")
    r = cur.fetchone()
    print(f"交易日历范围: {r[0]} ~ {r[1]}")

    cur = conn.execute(
        "SELECT SUBSTR(calendar_date,1,4) AS yr, COUNT(*), SUM(is_trading_day) "
        "FROM trade_calendar GROUP BY yr ORDER BY yr"
    )
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]} 条, {r[2]} 个交易日 ({r[1] - r[2]} 个休市日)")

    cur = conn.execute("SELECT COUNT(*) FROM trade_calendar")
    print(f"总计: {cur.fetchone()[0]} 条日历记录")
    conn.close()


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    elif "--force" in sys.argv:
        seed(force=True)
    else:
        seed(force=False)
