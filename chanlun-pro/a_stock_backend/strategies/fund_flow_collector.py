"""
资金流向历史数据采集器

两张独立表：
- stock_fund_flow      → 东方财富API成功获取的真实数据
- stock_fund_flow_local → API失败时本地推算的估算数据

采集策略：
- 每次请求间隔 2-5 秒随机
- 每10次后休息30秒
- 失败后间隔递增重试（3s, 6s, 12s）
- 支持从断点续采（--resume）
"""
import sys
import os
import json
import logging
import sqlite3
import time
import random
import subprocess
import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path

logger = logging.getLogger('fund_flow')

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

BASE_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
DAYS_BACK = 100

TBL_API = "stock_fund_flow"         # 东方财富API真实数据
TBL_LOCAL = "stock_fund_flow_local"  # 本地推算数据


def _parse_cn_float(val) -> float:
    """解析中文数字格式：'-4349.01万' → -43490100, '3.66亿' → 366000000"""
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").strip()
    if not s:
        return 0.0
    multiplier = 1
    if "亿" in s:
        multiplier = 100_000_000
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 10_000
        s = s.replace("万", "")
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _get_conn():
    return sqlite3.connect(DB_PATH)


def _ensure_table():
    conn = _get_conn()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TBL_API} (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            main_inflow REAL DEFAULT 0,
            main_pct REAL DEFAULT 0,
            big_inflow REAL DEFAULT 0,
            big_pct REAL DEFAULT 0,
            large_inflow REAL DEFAULT 0,
            large_pct REAL DEFAULT 0,
            medium_inflow REAL DEFAULT 0,
            medium_pct REAL DEFAULT 0,
            small_inflow REAL DEFAULT 0,
            small_pct REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TBL_LOCAL} (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            main_inflow REAL DEFAULT 0,
            main_pct REAL DEFAULT 0,
            big_inflow REAL DEFAULT 0,
            big_pct REAL DEFAULT 0,
            large_inflow REAL DEFAULT 0,
            large_pct REAL DEFAULT 0,
            medium_inflow REAL DEFAULT 0,
            medium_pct REAL DEFAULT 0,
            small_inflow REAL DEFAULT 0,
            small_pct REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"✅ 表 {TBL_API}(API) + {TBL_LOCAL}(本地推算) 就绪")


def _get_secid(symbol: str) -> str:
    sym = symbol.strip().zfill(6)
    return f"1.{sym}" if sym.startswith(("6", "9")) else f"0.{sym}"


_request_count = 0


def _rate_limit():
    global _request_count
    _request_count += 1
    if _request_count % 10 == 0:
        logger.info(f"⏸ 已请求{_request_count}次，休息30秒...")
        time.sleep(30)
    else:
        time.sleep(random.uniform(2, 5))


def _fetch_eastmoney(symbol: str, limit: int = DAYS_BACK) -> list:
    """调用东方财富资金流向API（带限流+重试）"""
    secid = _get_secid(symbol)
    url = (
        f"{BASE_URL}?secid={secid}"
        f"&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&lmt={limit}"
    )

    headers = [
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "User-Agent: Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
    ]

    _rate_limit()

    for attempt in range(2):
        ua = headers[attempt % len(headers)]
        curl_cmd = [
            "curl", "-s", "-4",
            url,
            "-H", ua,
            "-H", "Referer: https://data.eastmoney.com/",
            "--max-time", "10",
        ]
        try:
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0 or not result.stdout.strip():
                logger.debug(f"{symbol} 第{attempt+1}次空响应")
                time.sleep(2)
                continue
            data = json.loads(result.stdout)
        except Exception as e:
            logger.debug(f"{symbol} 第{attempt+1}次失败: {e}")
            time.sleep(2)
            continue

        if not isinstance(data, dict) or "data" not in data or not data["data"]:
            logger.debug(f"{symbol} 无数据")
            return []

        klines = data["data"].get("klines", [])
        if not klines:
            return []

        records = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 11:
                continue
            try:
                records.append({
                    "trade_date": parts[0].strip(),
                    "main_inflow": float(parts[1]),
                    "small_inflow": float(parts[2]),
                    "medium_inflow": float(parts[3]),
                    "large_inflow": float(parts[4]),
                    "big_inflow": float(parts[5]),
                    "main_pct": float(parts[6]),
                    "small_pct": float(parts[7]),
                    "medium_pct": float(parts[8]),
                    "large_pct": float(parts[9]),
                    "big_pct": float(parts[10]),
                })
            except (ValueError, IndexError):
                continue
        return records

    logger.info(f"{symbol} 重试结束，跳过")
    return []


def _save_records_api(symbol: str, records: list) -> int:
    """保存东方财富API数据 → stock_fund_flow"""
    if not records:
        return 0
    conn = _get_conn()
    written = 0
    for rec in records:
        try:
            conn.execute(f"""
                INSERT OR REPLACE INTO {TBL_API}
                (symbol, trade_date,
                 main_inflow, main_pct,
                 big_inflow, big_pct,
                 large_inflow, large_pct,
                 medium_inflow, medium_pct,
                 small_inflow, small_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, rec["trade_date"],
                rec.get("main_inflow", 0), rec.get("main_pct", 0),
                rec.get("big_inflow", 0), rec.get("big_pct", 0),
                rec.get("large_inflow", 0), rec.get("large_pct", 0),
                rec.get("medium_inflow", 0), rec.get("medium_pct", 0),
                rec.get("small_inflow", 0), rec.get("small_pct", 0),
            ))
            written += 1
        except Exception as e:
            logger.warning(f"{symbol} {rec['trade_date']}: {e}")
    conn.commit()
    conn.close()
    logger.info(f"✅ {symbol}: API数据写入 {written} 条 → {TBL_API}")
    return written


def _save_records_local(symbol: str, records: list) -> int:
    """保存本地推算数据 → stock_fund_flow_local"""
    if not records:
        return 0
    conn = _get_conn()
    written = 0
    for rec in records:
        try:
            conn.execute(f"""
                INSERT OR REPLACE INTO {TBL_LOCAL}
                (symbol, trade_date,
                 main_inflow, main_pct,
                 big_inflow, big_pct,
                 large_inflow, large_pct,
                 medium_inflow, medium_pct,
                 small_inflow, small_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, rec["trade_date"],
                rec.get("main_inflow", 0), rec.get("main_pct", 0),
                rec.get("big_inflow", 0), rec.get("big_pct", 0),
                rec.get("large_inflow", 0), rec.get("large_pct", 0),
                rec.get("medium_inflow", 0), rec.get("medium_pct", 0),
                rec.get("small_inflow", 0), rec.get("small_pct", 0),
            ))
            written += 1
        except Exception as e:
            logger.warning(f"{symbol} {rec['trade_date']}: {e}")
    conn.commit()
    conn.close()
    logger.info(f"✅ {symbol}: 本地推算写入 {written} 条 → {TBL_LOCAL}")
    return written


def collect_symbol(symbol: str, limit: int = DAYS_BACK) -> tuple:
    """采集单只股票的资金流向

    返回: (api_count, local_count)
      - api_count > 0  → 数据来自东方财富API，写入 stock_fund_flow
      - local_count > 0 → 数据来自本地推算，写入 stock_fund_flow_local
    """
    records = _fetch_eastmoney(symbol, limit)
    if records:
        return (_save_records_api(symbol, records), 0)

    records = _compute_from_local(symbol, limit)
    return (0, _save_records_local(symbol, records))


def _compute_from_local(symbol: str, limit: int = DAYS_BACK) -> list:
    """从 kline_cache + big_deal_summary 推算资金流向（stock_daily 已废弃）"""
    conn = _get_conn()
    try:
        bare = symbol
        daily = conn.execute(
            "SELECT trade_date, close, open, volume, amount FROM kline_cache "
            "WHERE period='daily' AND symbol IN (?, ?, ?) "
            "ORDER BY trade_date DESC LIMIT ?",
            (bare, f"SH.{bare}", f"SZ.{bare}", limit),
        ).fetchall()

        deals = {}
        try:
            for row in conn.execute(
                "SELECT trade_date, big_buy_amount FROM big_deal_summary "
                "WHERE symbol=? ORDER BY trade_date DESC LIMIT ?",
                (symbol, limit),
            ):
                deals[row[0]] = row[1]
        except Exception:
            pass

        records = []
        for row in daily:
            trade_date, close, open_px, volume, turnover = row
            if not turnover or turnover <= 0:
                continue

            # 方向判断：根据涨跌决定主力是流入还是流出
            # 阳线(close>open) → 主力买入(正), 阴线(close<open) → 主力卖出(负)
            # 涨幅越大方向越确定，用价格变化幅度缩放
            price_change = close - open_px
            direction = 1 if price_change >= 0 else -1
            # 涨跌幅比例越高，主力参与度越高（0.3~0.8）
            strength = min(abs(price_change) / (open_px or 1) * 10, 0.8)
            strength = max(strength, 0.3)  # 最小也有30%的确定性

            big_amt = deals.get(trade_date, 0)
            if big_amt <= 0 or abs(big_amt) < turnover * 0.02:
                # 无大单数据时，用成交额的 10~25% 估算主力参与，带方向
                base_ratio = 0.15 + strength * 0.1  # 0.18~0.23
                big_amt = turnover * base_ratio

            main_inflow = big_amt * direction
            big_inflow = main_inflow * 0.6
            large_inflow = main_inflow * 0.4
            medium_inflow = -main_inflow * 0.5
            small_inflow = -main_inflow * 0.5
            main_pct = round(abs(main_inflow) / turnover * 100, 2) if turnover else 0
            # 添加负号表示净流出
            if direction < 0:
                main_pct = -main_pct

            records.append({
                "trade_date": trade_date,
                "main_inflow": round(main_inflow, 2),
                "main_pct": main_pct,
                "big_inflow": round(big_inflow, 2),
                "big_pct": round(big_inflow / turnover * 100, 2) if turnover else 0,
                "large_inflow": round(large_inflow, 2),
                "large_pct": round(large_inflow / turnover * 100, 2) if turnover else 0,
                "medium_inflow": round(medium_inflow, 2),
                "medium_pct": round(medium_inflow / turnover * 100, 2) if turnover else 0,
                "small_inflow": round(small_inflow, 2),
                "small_pct": round(small_inflow / turnover * 100, 2) if turnover else 0,
            })

        return records
    except Exception as e:
        logger.warning(f"{symbol} 本地推算失败: {e}")
        return []
    finally:
        conn.close()


def collect_watch(limit_per_code: int = DAYS_BACK):
    """采集关注池股票"""
    conn = _get_conn()
    symbols = set()
    try:
        for (sym,) in conn.execute("SELECT symbol FROM favorites LIMIT 30"):
            symbols.add(sym)
    except Exception:
        pass
    try:
        for (sym,) in conn.execute("SELECT DISTINCT symbol FROM strategy_picks ORDER BY date DESC LIMIT 30"):
            symbols.add(sym)
    except Exception:
        pass
    try:
        for (sym,) in conn.execute("SELECT symbol FROM zt_pool WHERE date=(SELECT MAX(date) FROM zt_pool)"):
            symbols.add(sym)
    except Exception:
        pass
    conn.close()

    total_api, total_local = 0, 0
    sym_list = list(symbols)
    logger.info(f"关注池共 {len(sym_list)} 只，开始采集...")
    for i, sym in enumerate(sym_list, 1):
        api_cnt, local_cnt = collect_symbol(sym, limit_per_code)
        total_api += api_cnt
        total_local += local_cnt
        if i % 10 == 0:
            logger.info(f"  进度: {i}/{len(sym_list)}, API={total_api} 本地={total_local}")
        time.sleep(0.3)
    return total_api, total_local


def collect_batch(symbols: list, limit_per_code: int = DAYS_BACK):
    """批量采集指定列表"""
    total_api, total_local = 0, 0
    for i, sym in enumerate(symbols, 1):
        api_cnt, local_cnt = collect_symbol(sym, limit_per_code)
        total_api += api_cnt
        total_local += local_cnt
        if i % 10 == 0:
            logger.info(f"  进度: {i}/{len(symbols)}, API={total_api} 本地={total_local}")
        time.sleep(0.3)
    return total_api, total_local


PROGRESS_FILE = os.path.expanduser("~/.chanlun_pro/fund_flow_progress.json")


def _load_progress() -> dict:
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"completed": [], "last_idx": 0, "total": 0}


def _save_progress(idx: int, total: int, symbol: str):
    prog = _load_progress()
    prog["last_idx"] = idx
    prog["total"] = total
    if symbol not in prog["completed"]:
        prog["completed"].append(symbol)
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(prog, f, ensure_ascii=False)


def _trim_symbol(symbol: str, max_days: int = DAYS_BACK):
    """删除某只股票超出 max_days 的旧数据（两张表都处理）"""
    conn = _get_conn()
    try:
        for tbl in (TBL_API, TBL_LOCAL):
            row = conn.execute(
                f"SELECT MIN(trade_date) FROM (SELECT trade_date FROM {tbl} WHERE symbol=? ORDER BY trade_date DESC LIMIT ?)",
                (symbol, max_days)
            ).fetchone()
            if row and row[0]:
                cutoff = row[0]
                deleted = conn.execute(
                    f"DELETE FROM {tbl} WHERE symbol=? AND trade_date < ?",
                    (symbol, cutoff)
                ).rowcount
                if deleted > 0:
                    logger.info(f"  ✂ {symbol}: {tbl} 修剪 {deleted} 条 (保留最新{max_days}天)")
        conn.commit()
    except Exception as e:
        logger.warning(f"{symbol} 修剪失败: {e}")
    finally:
        conn.close()


def collect_all(resume: bool = False, max_stocks: int = None):
    """全市场采集（按 stock_daily 顺序，断点续采）

    Args:
        resume: 是否从上次中断位置继续
        max_stocks: 最多采多少只（None=全市场）
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND source='tencent_fq' "
        "AND symbol NOT LIKE '%.%' AND substr(symbol,1,1) IN ('0','3','6','9') ORDER BY symbol"
    ).fetchall()
    conn.close()

    symbols = [r[0] for r in rows]
    total_all = len(symbols)
    logger.info(f"📊 全市场共 {total_all} 只股票（按 stock_daily 顺序）")

    if max_stocks and max_stocks < total_all:
        symbols = symbols[:max_stocks]
        total_all = len(symbols)
        logger.info(f"  限制采集 {total_all} 只")

    start_idx = 0
    if resume:
        prog = _load_progress()
        if prog.get("last_idx", 0) > 0:
            start_idx = prog["last_idx"]
            logger.info(f"↩ 断点续采: 上次完成 {len(prog.get('completed',[]))} 只 (索引 {start_idx}/{total_all})")
            symbols = symbols[start_idx:]
            logger.info(f"  剩余 {len(symbols)} 只")

    total_api, total_local, errors = 0, 0, 0
    start_time = datetime.now()

    for i, sym in enumerate(symbols, 1):
        global_idx = start_idx + i
        tick_start = time.time()
        api_cnt, local_cnt = collect_symbol(sym)

        total_api += api_cnt
        total_local += local_cnt
        if api_cnt == 0 and local_cnt == 0:
            errors += 1

        _trim_symbol(sym)

        if i % 10 == 0:
            elapsed_total = (datetime.now() - start_time).total_seconds()
            rate = i / elapsed_total * 60 if elapsed_total > 0 else 0
            eta_min = (len(symbols) - i) / (rate + 0.01) if rate > 0 else 999
            logger.info(
                f"📈 [{global_idx}/{total_all}] {sym} → "
                f"API={total_api} 本地={total_local}条 "
                f"({rate:.1f}只/分 ETA {eta_min:.0f}分) "
                f"失败{errors}/{i}"
            )
            _save_progress(global_idx, total_all, sym)

        if i % 50 == 0:
            _save_progress(global_idx, total_all, sym)

    elapsed = datetime.now() - start_time
    logger.info(f"🎉 全市场采集完成! API={total_api} 本地={total_local}条, "
                f"耗时 {elapsed.total_seconds()/60:.1f} 分")
    _save_progress(total_all, total_all, symbols[-1] if symbols else "")
    return total_api, total_local


# ── 多模式懒加载（A轮换） ──
_LAZY_STATE_PATH = os.path.expanduser("~/.chanlun_pro/fund_flow_lazy_state.json")
_LAZY_MODES = ["ths_market", "ths_bigdeal", "eastmoney_recovery"]


def _lazy_load_state() -> dict:
    """读懒加载状态"""
    try:
        with open(_LAZY_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"mode_idx": 0, "today": "", "ths_today_done": False, "bigdeal_today_done": False}


def _lazy_save_state(st: dict):
    """写懒加载状态"""
    os.makedirs(os.path.dirname(_LAZY_STATE_PATH), exist_ok=True)
    with open(_LAZY_STATE_PATH, "w") as f:
        json.dump(st, f)


def _ensure_bigdeal_table():
    """确保 big_deal_summary 表存在"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS big_deal_summary (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            big_buy_count INTEGER DEFAULT 0,
            big_buy_amount REAL DEFAULT 0,
            big_buy_lots REAL DEFAULT 0,
            total_lots REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.commit()
    conn.close()


def _lazy_ths_market() -> str:
    """模式A：同花顺全市场资金流（每日一次）"""
    today = date.today().isoformat()
    conn = _get_conn()
    # 检查今天是否已有同花顺数据（取一条sample）
    has = conn.execute(
        f"SELECT 1 FROM {TBL_API} WHERE trade_date=? AND symbol='000001' LIMIT 1",
        (today,)
    ).fetchone()
    conn.close()
    if has:
        return f"⏭ {today} 已有数据，跳过同花顺全市场采集"

    logger.info(f"📡 [模式A] 同花顺全市场资金流 {today}")
    try:
        df = ak.stock_fund_flow_individual(symbol='即时')
        if df is None or df.empty:
            return "❌ 同花顺返回空数据"
    except Exception as e:
        return f"❌ 同花顺请求失败: {e}"

    written = 0
    conn = _get_conn()
    try:
        for _, row in df.iterrows():
            code = str(row.get("股票代码", "")).strip()
            if not code or len(code) < 6:
                continue
            # 标准化代码（SZ.000001 / SH.600000）
            if code.startswith(("6", "9")):
                sym = f"SH.{code}"
            elif code.startswith(("0", "3", "2")):
                sym = f"SZ.{code}"
            else:
                continue

            net = _parse_cn_float(row.get("净额", 0))
            inflow = _parse_cn_float(row.get("流入资金", 0))
            outflow = _parse_cn_float(row.get("流出资金", 0))
            turnover = _parse_cn_float(row.get("成交额", 0))
            main_pct = round(abs(net) / turnover * 100, 2) if turnover > 0 else 0
            if net < 0:
                main_pct = -main_pct

            conn.execute(f"""
                INSERT OR REPLACE INTO {TBL_API}
                (symbol, trade_date, main_inflow, main_pct,
                 big_inflow, big_pct, large_inflow, large_pct,
                 medium_inflow, medium_pct, small_inflow, small_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sym, today, round(net, 2), main_pct,
                round(inflow * 0.4, 2), round(abs(net) / turnover * 40, 2) if turnover > 0 else 0,
                0, 0, 0, 0, 0, 0,
            ))
            written += 1

        conn.commit()
        logger.info(f"  ✅ 写入 {written} 只股票资金流")
        return f"✅ [模式A] 同花顺全市场: 写入 {written} 只"
    except Exception as e:
        conn.rollback()
        return f"❌ [模式A] 写入失败: {e}"
    finally:
        conn.close()


def _lazy_ths_bigdeal() -> str:
    """模式B：同花顺大单交易（每日一次）"""
    _ensure_bigdeal_table()
    today = date.today().isoformat()

    logger.info(f"📡 [模式B] 同花顺大单交易 {today}")
    try:
        df = ak.stock_fund_flow_big_deal()
        if df is None or df.empty:
            return "❌ 同花顺大单返回空数据"
    except Exception as e:
        return f"❌ 同花顺大单请求失败: {e}"

    # 按股票+日期聚合：买盘笔数、金额
    df["日期"] = df["成交时间"].str[:10]
    agg = df.groupby(["股票代码", "日期"]).agg(
        big_buy_count=("大单性质", lambda x: sum(1 for v in x if "买" in str(v))),
        big_buy_amount=("成交额", lambda x: sum(float(v) for v in x if v)),
        total_lots=("成交量", "sum"),
        total_amount=("成交额", "sum"),
    ).reset_index()

    written = 0
    conn = _get_conn()
    try:
        for _, row in agg.iterrows():
            code = str(row["股票代码"]).strip().zfill(6)
            sym = f"SH.{code}" if code.startswith(("6", "9")) else f"SZ.{code}"
            trade_date = row["日期"]

            conn.execute(f"""
                INSERT OR REPLACE INTO big_deal_summary
                (symbol, trade_date, big_buy_count, big_buy_amount, big_buy_lots, total_lots, total_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sym, trade_date,
                int(row["big_buy_count"]),
                round(float(row["big_buy_amount"]), 2),
                round(float(row["big_buy_amount"]) / 100, 0),
                round(float(row["total_lots"]), 0),
                round(float(row["total_amount"]), 2),
            ))
            written += 1

        conn.commit()
        logger.info(f"  ✅ 大单交易写入 {written} 条")
        return f"✅ [模式B] 同花顺大单: 写入 {written} 条"
    except Exception as e:
        conn.rollback()
        return f"❌ [模式B] 写入失败: {e}"
    finally:
        conn.close()


def _lazy_eastmoney_recovery(count: int = 5) -> str:
    """模式C：东方财富API抢救（改参数重试）"""
    conn = _get_conn()
    rows = conn.execute(f"""
        SELECT DISTINCT l.symbol FROM {TBL_LOCAL} l
        LEFT JOIN {TBL_API} a ON l.symbol = a.symbol
        WHERE a.symbol IS NULL
        ORDER BY l.symbol
        LIMIT ?
    """, (count,)).fetchall()
    conn.close()

    symbols = [r[0] for r in rows]
    if not symbols:
        return "✅ [模式C] 所有股票已有API数据"

    logger.info(f"📡 [模式C] 东方财富抢救: {len(symbols)} 只")
    ok = 0
    for sym in symbols:
        wait = random.uniform(15, 30)
        logger.info(f"  ⏳ {sym}: 等待{wait:.0f}s")
        time.sleep(wait)

        # 尝试3种参数组合
        for params in [
            {"ipv": "-4"},                          # 原参数
            {"ipv": "-6"},                          # IPv6
            {"ipv": ""},                            # 自动
        ]:
            secid = _get_secid(sym)
            url = f"{BASE_URL}?secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&lmt={DAYS_BACK}"
            curl_cmd = ["curl", "-s"]
            if params["ipv"]:
                curl_cmd.append(params["ipv"])
            curl_cmd += [
                url, "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "-H", "Referer: https://data.eastmoney.com/",
                "--max-time", "10",
            ]
            try:
                result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=15)
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    if isinstance(data, dict) and data.get("data") and data["data"].get("klines"):
                        records = []
                        for line in data["data"]["klines"]:
                            parts = line.split(",")
                            if len(parts) >= 11:
                                records.append({
                                    "trade_date": parts[0].strip(),
                                    "main_inflow": float(parts[1]),
                                    "small_inflow": float(parts[2]),
                                    "medium_inflow": float(parts[3]),
                                    "large_inflow": float(parts[4]),
                                    "big_inflow": float(parts[5]),
                                    "main_pct": float(parts[6]),
                                    "small_pct": float(parts[7]),
                                    "medium_pct": float(parts[8]),
                                    "large_pct": float(parts[9]),
                                    "big_pct": float(parts[10]),
                                })
                        if records:
                            saved = _save_records_api(sym, records)
                            if saved > 0:
                                conn = _get_conn()
                                conn.execute(f"DELETE FROM {TBL_LOCAL} WHERE symbol=?", (sym,))
                                conn.commit()
                                conn.close()
                                ok += 1
                                logger.info(f"  ✅ {sym}: 成功(ipv={params['ipv']}), {saved}条")
                                break
            except Exception as e:
                logger.debug(f"  ⏭ {sym} {params['ipv']}失败: {e}")
                continue

    msg = f"✅ [模式C] 东方财富抢救: {ok}/{len(symbols)} 只"
    if ok < len(symbols):
        msg += f" ({len(symbols)-ok}只下次再试)"
    return msg


_LAZY_MODES = ["ths_market", "bigdeal", "daily_incr"]


def _lazy_load_state() -> dict:
    p = Path(_LAZY_STATE_PATH)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _lazy_save_state(st: dict):
    Path(_LAZY_STATE_PATH).write_text(json.dumps(st, ensure_ascii=False))


def collect_lazy_multi_mode() -> str:
    """多模式懒加载：每小时轮换一种策略

    轮换顺序: 同花顺全市场(A) → 同花顺大单(B) → 东方财富每日增量(D, 200只/次)
    每日限定: A/B 每天只跑一次; D 每次跑200只
    """
    _ensure_table()
    _ensure_bigdeal_table()

    st = _lazy_load_state()
    today = date.today().isoformat()

    # 今天首次运行：重置今日状态（非交易日跳过）
    if st.get("today") != today:
        st["today"] = today
        st["ths_today_done"] = False
        st["bigdeal_today_done"] = False
        st["mode_idx"] = 0

    mode_idx = st.get("mode_idx", 0)
    result = ""

    for _ in range(len(_LAZY_MODES)):  # 最多循环一轮
        mode = _LAZY_MODES[mode_idx]
        mode_idx = (mode_idx + 1) % len(_LAZY_MODES)

        if mode == "ths_market":
            if st["ths_today_done"]:
                continue
            result = _lazy_ths_market()
            if result and "❌" not in result:
                st["ths_today_done"] = True

        elif mode == "bigdeal":
            if st["bigdeal_today_done"]:
                continue
            result = _lazy_ths_bigdeal()
            if result and "❌" not in result:
                st["bigdeal_today_done"] = True

        elif mode == "daily_incr":
            result = collect_daily_incremental(batch=200)

        if result:
            break  # 执行了一个模式

    st["mode_idx"] = mode_idx
    _lazy_save_state(st)
    logger.info(f"🔄 懒加载轮换完成 ({result})")
    return result


# 兼容旧函数名
collect_api_lazy = collect_lazy_multi_mode


# ── 板块资金流表 ──
TBL_SECTOR = "stock_sector_fund_flow"


def _ensure_sector_flow_table():
    conn = _get_conn()
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {TBL_SECTOR} (
        sector_code TEXT NOT NULL,
        sector_name TEXT NOT NULL,
        sector_type TEXT NOT NULL,    -- 行业/概念/地域
        trade_date TEXT NOT NULL,
        indicator TEXT NOT NULL,      -- 今日/5日/10日
        index_price REAL,
        change_pct REAL,
        main_inflow REAL DEFAULT 0,
        main_pct REAL DEFAULT 0,
        big_inflow REAL DEFAULT 0,    -- 超大单
        big_pct REAL DEFAULT 0,
        large_inflow REAL DEFAULT 0,  -- 大单
        large_pct REAL DEFAULT 0,
        medium_inflow REAL DEFAULT 0,
        medium_pct REAL DEFAULT 0,
        small_inflow REAL DEFAULT 0,
        small_pct REAL DEFAULT 0,
        leader_name TEXT DEFAULT '',
        leader_code TEXT DEFAULT '',
        PRIMARY KEY (sector_code, sector_type, indicator, trade_date)
    )""")
    conn.commit()
    conn.close()
    logger.info(f"✅ {TBL_SECTOR} 表就绪")


def collect_sector_fund_flow(indicator: str = "今日") -> str:
    """采集东方财富板块资金流排行（行业+概念+地域）"""
    _ensure_sector_flow_table()
    today = date.today().isoformat()

    sector_types = {
        "行业": "t:2",
        "概念": "t:3",
        "地域": "t:1",
    }
    referers = {
        "t:2": "https://data.eastmoney.com/bkzj/hy.html",
        "t:3": "https://data.eastmoney.com/bkzj/gn.html",
        "t:1": "https://data.eastmoney.com/bkzj/dy.html",
    }
    indicator_map = {
        "今日": ("f62", "1", "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124"),
        "5日": ("f164", "5", "f12,f14,f2,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258,f124"),
        "10日": ("f174", "10", "f12,f14,f2,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261,f124"),
    }
    fid0, stat, fields = indicator_map[indicator]

    total_ok = 0
    for stype, fs_suffix in sector_types.items():
        url = ("https://push2.eastmoney.com/api/qt/clist/get"
               f"?pn=1&pz=500&po=1&np=1"
               f"&ut=b2884a393a59ad64002292a3e90d46a5"
               f"&fltt=2&invt=2"
               f"&fid0={fid0}&fs=m:90+{fs_suffix}"
               f"&stat={stat}&fields={fields}&rt=1")

        curl_cmd = ["curl", "-s", "-4", url,
                    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "-H", f"Referer: {referers[fs_suffix]}",
                    "--max-time", "15"]
        try:
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=20)
            if result.returncode != 0 or not result.stdout.strip():
                logger.warning(f"  ⏭ {stype}资金流: 空响应")
                continue
            data = json.loads(result.stdout)
            items = data.get("data", {}).get("diff", [])
            if not items:
                continue
        except Exception as e:
            logger.warning(f"  ⏭ {stype}资金流请求失败: {e}")
            continue

        conn = _get_conn()
        try:
            ok = 0
            for item in items:
                code = str(item.get("f12", ""))
                name = str(item.get("f14", ""))
                if not code:
                    continue
                def _f(k):
                    v = item.get(k, 0)
                    return float(v) if v not in (None, "-", "") else 0.0
                conn.execute(f"""INSERT OR REPLACE INTO {TBL_SECTOR}
                    (sector_code, sector_name, sector_type, trade_date, indicator,
                     index_price, change_pct,
                     main_inflow, main_pct, big_inflow, big_pct,
                     large_inflow, large_pct, medium_inflow, medium_pct,
                     small_inflow, small_pct,
                     leader_name, leader_code)
                    VALUES (?,?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?)""", (
                    code, name, stype, today, indicator,
                    _f("f2"), _f("f3"),
                    _f("f62"), _f("f184"), _f("f66"), _f("f69"),
                    _f("f72"), _f("f75"), _f("f78"), _f("f81"),
                    _f("f84"), _f("f87"),
                    str(item.get("f204", "")), str(item.get("f205", "")),
                ))
                ok += 1
            conn.commit()
            total_ok += ok
            logger.info(f"  ✅ {stype}资金流: {ok} 板块")
        except Exception as e:
            conn.rollback()
            logger.warning(f"  ❌ {stype}写入失败: {e}")
        finally:
            conn.close()

    return f"✅ 板块资金流采集完成: {total_ok} 条 ({indicator})"


def collect_daily_incremental(batch: int = 200) -> str:
    """每日增量采集：批量扫描 kline_cache 中有日线数据的股票，补当天资金流向

    用 lmt=3 (最近3天) 快速获取，避免全量历史。
    """
    _ensure_table()
    today = date.today().isoformat()
    conn = _get_conn()

    # 获取全市场有日线数据的股票（不限 source，去重）
    stocks = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' "
        "AND symbol NOT LIKE '%.%' "  # 只用裸码
        "ORDER BY symbol"
    ).fetchall()
    all_symbols = [r[0] for r in stocks]
    conn.close()

    # 过滤已采集今天的
    need = []
    conn = _get_conn()
    for sym in all_symbols:
        has = conn.execute(
            f"SELECT 1 FROM {TBL_API} WHERE symbol=? AND trade_date=? LIMIT 1",
            (sym, today)
        ).fetchone()
        if not has:
            need.append(sym)
            if len(need) >= batch:
                break
    conn.close()

    if not need:
        return f"✅ 今日全市场资金流向已齐全 ({len(all_symbols)}只)"

    logger.info(f"📡 [每日增量] 补 {len(need)} 只/{len(all_symbols)} 只股票今日资金流向")
    ok = 0
    fail = 0

    for i, sym in enumerate(need):
        time.sleep(random.uniform(1.5, 3.0))

        secid = _get_secid(sym)
        url = f"{BASE_URL}?secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65&lmt=3"
        curl_cmd = ["curl", "-s", "-4", url,
                    "-H", "User-Agent: Mozilla/5.0",
                    "-H", "Referer: https://data.eastmoney.com/",
                    "--max-time", "10"]
        try:
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0 or not result.stdout.strip():
                fail += 1
                if (i + 1) % 20 == 0:
                    logger.info(f"  ⏳ {i+1}/{len(need)} 完成{ok}失败{fail}")
                continue
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or not data.get("data") or not data["data"].get("klines"):
                fail += 1
                continue

            records = []
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) < 11:
                    continue
                try:
                    records.append({
                        "trade_date": parts[0].strip(),
                        "main_inflow": float(parts[1]),
                        "small_inflow": float(parts[2]),
                        "medium_inflow": float(parts[3]),
                        "large_inflow": float(parts[4]),
                        "big_inflow": float(parts[5]),
                        "main_pct": float(parts[6]),
                        "small_pct": float(parts[7]),
                        "medium_pct": float(parts[8]),
                        "large_pct": float(parts[9]),
                        "big_pct": float(parts[10]),
                    })
                except (ValueError, IndexError):
                    continue

            if records:
                saved = _save_records_api(sym, records)
                if saved > 0:
                    # 清理本地推算数据
                    c2 = _get_conn()
                    c2.execute(f"DELETE FROM {TBL_LOCAL} WHERE symbol=?", (sym,))
                    c2.commit()
                    c2.close()
                    ok += 1

            if ok + fail > 0 and (i + 1) % 20 == 0:
                logger.info(f"  ⏳ {i+1}/{len(need)} {ok}成功 {fail}失败")

        except Exception as e:
            fail += 1
            if (i + 1) % 50 == 0:
                logger.debug(f"  {sym}: {e}")

    msg = f"✅ [每日增量] {ok}成功 {fail}失败 (本批{len(need)}只, 全市场{len(all_symbols)}只)"
    return msg


# ── 命令行入口 ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    import argparse
    parser = argparse.ArgumentParser(description="资金流向采集器")
    parser.add_argument("--code", type=str, help="单只股票代码")
    parser.add_argument("--limit", type=int, default=DAYS_BACK, help="返回天数")
    parser.add_argument("--watch", action="store_true", help="采关注池")
    parser.add_argument("--all", action="store_true", help="全量采集（全市场按 stock_daily 顺序）")
    parser.add_argument("--resume", action="store_true", help="断点续采")
    parser.add_argument("--max", type=int, default=None, help="最多采集N只（测试用）")
    parser.add_argument("--init-db", action="store_true", help="仅初始化表")
    parser.add_argument("--status", action="store_true", help="查看采集进度")
    parser.add_argument("--api-lazy", type=int, nargs="?", const=5, default=0,
                        help="懒加载模式: 慢慢替换为真实API数据 (默认5只/次)")
    parser.add_argument("--daily-incremental", type=int, nargs="?", const=200, default=0,
                        help="每日增量采集: 补当天资金流向 (默认200只/次)")
    parser.add_argument("--sector-flow", action="store_true",
                        help="采集板块资金流排行（行业+概念+地域）")

    args = parser.parse_args()

    _ensure_table()

    if args.init_db:
        sys.exit(0)

    if args.status:
        prog = _load_progress()
        print(f"采集进度: {len(prog.get('completed',[]))}/{prog.get('total',0)} 只")
        print(f"最后索引: {prog.get('last_idx',0)}")
        print(f"最后股票: {prog.get('completed',[''])[-1] if prog.get('completed') else '无'}")
        sys.exit(0)

    if args.sector_flow:
        logger.info("📊 采集板块资金流排行...")
        result = collect_sector_fund_flow(indicator="今日")
        logger.info(f"✅ {result}")
    elif args.daily_incremental:
        logger.info(f"📡 [每日增量] 采集 {args.daily_incremental} 只...")
        result = collect_daily_incremental(batch=args.daily_incremental)
        logger.info(f"✅ {result}")
    elif args.code:
        api_cnt, local_cnt = collect_symbol(args.code, args.limit)
        logger.info(f"✅ 完成: API={api_cnt} 本地={local_cnt} 条")
    elif args.watch:
        total_api, total_local = collect_watch(args.limit)
        logger.info(f"✅ 关注池完成: API={total_api} 本地={total_local} 条")
    elif args.all:
        logger.info("🚀 开始全市场资金流向采集（预计6-10小时）")
        total_api, total_local = collect_all(resume=args.resume, max_stocks=args.max)
        logger.info(f"✅ 全市场完成: API={total_api} 本地={total_local} 条")
    elif args.api_lazy:
        logger.info(f"🐌 懒加载多模式轮换 (A:同花顺全市场/B:大单/C:东方财富抢救)")
        result = collect_lazy_multi_mode()
        logger.info(f"✅ {result}")
    else:
        parser.print_help()
