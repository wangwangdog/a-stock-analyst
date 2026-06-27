#!/usr/bin/env python3
"""
盘口异动数据获取与解析

从 AKShare 获取当日盘口异动分类数据，解析后生成 Excel 文件，
并自动调用 wsqllite.py 写入 stock_records 表、调用 hzeveryday.py 汇总到 hzeveryday 表。

所有外部调用均带 timeout 保护，超时时优雅降级。
"""

import akshare as ak
import pandas as pd
import os
import re
import sys
import shutil
import subprocess
import threading
import logging
from pathlib import Path
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 外部调用 timeout 工具 ──


def _run_with_timeout(func, args=(), kwargs=None, timeout_sec=10, default=None, name=""):
    """带 timeout 执行函数，超时返回 default 值"""
    if kwargs is None:
        kwargs = {}
    result = [None]
    exception = [None]
    done = threading.Event()

    def worker():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    if done.wait(timeout=timeout_sec):
        if exception[0]:
            logger.warning(f"{name} 执行失败: {exception[0]}")
            return default
        return result[0]
    else:
        logger.warning(f"{name} 超时 ({timeout_sec}s)，跳过")
        return default


def ak_stock_changes(symbol: str, timeout: int = 10):
    """带 timeout 的 ak.stock_changes_em() 调用"""
    return _run_with_timeout(
        ak.stock_changes_em,
        kwargs={"symbol": symbol},
        timeout_sec=timeout,
        default=None,
        name=f"stock_changes_em({symbol})"
    )


# ── 交易日判断 ──


def _is_trading_day() -> bool:
    """通过 TradingCalendar 判断今天是不是交易日，非交易日直接退出。

    使用 merged DB 中的 trade_calendar 表（无需外部网络）。
    仅在 merged DB 不可用时回退到 heuristic 规则。
    """
    try:
        # 使用 importlib 直接加载 trading_calendar 模块，避免 __init__ 的副作用
        import importlib.util
        _BASE_DIR = Path(__file__).resolve().parent.parent.parent / "src"
        spec = importlib.util.spec_from_file_location(
            "trading_calendar",
            str(_BASE_DIR / "chanlun" / "utils" / "trading_calendar.py"),
        )
        tc_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tc_mod)
        cal = tc_mod.get_calendar()
        today = datetime.now().strftime("%Y-%m-%d")
        return cal.is_trading_day(today)
    except Exception as e:
        logger.warning(f"交易日历模块加载失败: {e}，默认按交易日处理")
        return True


def _timeout_main(timeout_sec=60):
    """全局 main 函数超时保护装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]
            done = threading.Event()

            def worker():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
                finally:
                    done.set()

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            if done.wait(timeout=timeout_sec):
                if exception[0]:
                    raise exception[0]
                return result[0]
            else:
                logger.error(f"主程序执行超时 ({timeout_sec}s)，强制退出")
                sys.exit(1)
        return wrapper
    return decorator


# ── 解析工具 ──


def _extract_num(s: str) -> float:
    return float(re.sub(r'[^\d.\-]', '', s))


# ── 主逻辑 ──


@_timeout_main(120)
def main():
    # ── 交易日判断（定时任务入口）──
    if not _is_trading_day():
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"📅 {today} 非交易日，跳过盘口异动数据获取")
        sys.exit(0)

    # ---------- 1. 所有异动分类 ----------
    symbols = [
        '火箭发射', '快速反弹', '大笔买入', '封涨停板',
        '有大买盘', '竞价上涨', '高开5日线', '向上缺口', '60日新高',
        '60日大幅上涨', '加速下跌', '高台跳水', '大笔卖出', '封跌停板',
        '有大卖盘', '竞价下跌', '低开5日线', '向下缺口',
        '60日新低', '60日大幅下跌'
    ]

    # ---------- 2. 输出文件夹 ----------
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(SCRIPT_DIR, '盘口异动_分类解析')
    excel_dir = os.path.join(SCRIPT_DIR, 'excel_files')
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(excel_dir, exist_ok=True)
    date_tag = datetime.now().strftime('%Y%m%d')

    print(f"输出目录: {output_dir}")
    print(f"共 {len(symbols)} 个分类\n")

    # ---------- 3. 逐类获取并解析（所有调用带 timeout） ----------
    has_any_data = False
    for sym in symbols:
        print(f'处理: {sym} ...', end=' ')
        df = ak_stock_changes(sym, timeout=10)
        if df is None:
            print('⚠ 数据源不可用（超时或失败）')
            continue

        if df.empty:
            print('无数据')
            continue

        if '相关信息' not in df.columns or '时间' not in df.columns:
            print('缺少必要列，跳过')
            continue

        # 解析每一行的"相关信息"
        parsed_rows = []
        for _, row in df.iterrows():
            info = str(row['相关信息']).strip()
            if not info or info == 'nan':
                continue

            parts = [p.strip() for p in info.split(',')]
            if len(parts) < 3:
                continue

            try:
                qty = _extract_num(parts[0])
                price = _extract_num(parts[1])
                change = _extract_num(parts[2])
            except ValueError:
                continue

            amount = qty * price

            parsed_rows.append({
                '股票代码': row.get('代码', ''),
                '股票名称': row.get('名称', ''),
                '买入数量': qty,
                '单价': price,
                '涨跌幅': change,
                '金额(单价*数量)': amount,
                '买入时间': row['时间']
            })

        # 保存该类别的解析结果
        if parsed_rows:
            result_df = pd.DataFrame(parsed_rows).sort_values('买入时间')
            safe_name = sym.replace('/', '_')
            filename = f'盘口异动解析_{date_tag}_{safe_name}.xlsx'
            filepath = os.path.join(output_dir, filename)
            result_df.to_excel(filepath, index=False, engine='openpyxl')
            has_any_data = True
            print(f'已生成 {len(parsed_rows)} 条明细')
        else:
            print('无有效解析数据')

    if not has_any_data:
        print(f'\n⚠ 所有分类均无有效数据，可能数据源不可用')
        # 不退出，继续尝试有大买盘

    print(f'\n✅ 完成！所有解析文件保存在：{output_dir}')

    # ---------- 4. 复制"大笔买入"文件到 excel_files 并入库 ----------
    print('\n--- 筛选大笔买入文件 ---')
    buy_files = [f for f in os.listdir(output_dir)
                 if f.endswith('.xlsx') and '大笔买入' in f and date_tag in f]

    for f in buy_files:
        src = os.path.join(output_dir, f)
        dst = os.path.join(excel_dir, f)
        shutil.copy2(src, dst)
        print(f'复制: {f}')

    if buy_files:
        print(f'\n--- 调用 wsqllite.py 写入数据库 ---')
        wsqllite_path = os.path.join(SCRIPT_DIR, 'wsqllite.py')

        def _run_wsqllite():
            result = subprocess.run(['python3', wsqllite_path], capture_output=True, text=True, cwd=SCRIPT_DIR)
            return result

        ws_result = _run_with_timeout(_run_wsqllite, timeout_sec=30, name="wsqllite.py")
        if ws_result is not None:
            print(ws_result.stdout)
            if ws_result.returncode != 0:
                print(f'wsqllite.py 错误: {ws_result.stderr}')
            else:
                print('wsqllite.py 执行成功 ✅')
        else:
            print('⚠ wsqllite.py 执行超时，跳过')

        print(f'\n--- 调用 hzeveryday.py 汇总数据 ---')
        hz_path = os.path.join(SCRIPT_DIR, 'hzeveryday.py')

        def _run_hz():
            return subprocess.run(['python3', hz_path], capture_output=True, text=True, cwd=SCRIPT_DIR)

        hz_result = _run_with_timeout(_run_hz, timeout_sec=30, name="hzeveryday.py")
        if hz_result is not None:
            print(hz_result.stdout)
            if hz_result.returncode != 0:
                print(f'hzeveryday.py 错误: {hz_result.stderr}')
            else:
                print('hzeveryday.py 执行成功 ✅')
        else:
            print('⚠ hzeveryday.py 执行超时，跳过')

        # 将 excel_files 中的文件移回原目录
        print(f'\n--- 清理：将 excel_files 中的文件移回原目录 ---')
        for f in buy_files:
            src = os.path.join(excel_dir, f)
            dst = os.path.join(output_dir, f)
            os.replace(src, dst)
            print(f'移回: {f}')
    else:
        print('今日无大笔买入数据，跳过入库')

    # ---------- 5. 有大买盘 → big_buy_summary 表 ----------
    print('\n--- 提取有大买盘数据 → big_buy_summary ---')
    df_big = ak_stock_changes('有大买盘', timeout=10)

    if df_big is not None and not df_big.empty:
        DB = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')
        import sqlite3
        conn = sqlite3.connect(DB)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS big_buy_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT,
                symbol TEXT,
                name TEXT,
                time TEXT,
                qty REAL,
                price REAL,
                change REAL,
                amount REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bbs_date ON big_buy_summary(trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bbs_symbol ON big_buy_summary(symbol)")

        today_str = datetime.now().strftime('%Y-%m-%d')
        inserted = 0
        for _, row in df_big.iterrows():
            try:
                info = str(row['相关信息']).strip()
                parts = [p.strip() for p in info.split(',')]
                if len(parts) < 4:
                    continue
                conn.execute(
                    "INSERT INTO big_buy_summary (trade_date, symbol, name, time, qty, price, change, amount) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (today_str, str(row['代码']), str(row['名称']), str(row['时间']),
                     float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
                )
                inserted += 1
            except (ValueError, KeyError):
                continue
        conn.commit()
        conn.close()
        print(f'✅ big_buy_summary: 写入 {inserted} 条有大买盘记录')
    else:
        print('今日无有大买盘数据')


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"pkyd.py 执行异常: {e}")
        sys.exit(1)
