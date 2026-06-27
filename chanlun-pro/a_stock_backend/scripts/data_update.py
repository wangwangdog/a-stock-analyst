"""
增量数据更新脚本
- 交易日 17:00 由 cron 调用
- 增量更新全市场日线 + 15min/30min/60min 分钟线
- 只更新最近 30 个交易日，已有数据跳过
- 数据源优先级: baostock(日线) > AKShare(日线+分钟线)
"""
import sys
import time
import warnings
import socket
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from data.cache import _get_conn, save_kline
from config import REQUEST_INTERVAL

# 尝试导入
try:
    import akshare as ak
    AKSHARE_OK = True
except ImportError:
    AKSHARE_OK = False
    ak = None
try:
    import baostock as bs
    BAOSTOCK_OK = True
except ImportError:
    BAOSTOCK_OK = False
    bs = None


BATCH_SIZE = 100
INTER_STOCK = 0.15
INTER_BATCH = 3
FETCH_DAYS_DAILY = 45   # 日线：45 自然日覆盖 ~30 交易日
FETCH_DAYS_MINUTE = 45  # 分钟线：同上

# Baostock 会话复用
_BS_CONNECTED = False


# ──────────────────────────────────────────
# 股票列表
# ──────────────────────────────────────────
def get_all_stocks_akshare() -> pd.DataFrame:
    """从 AKShare 获取 A 股股票列表"""
    if not AKSHARE_OK:
        return pd.DataFrame()
    try:
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            mask = df["code"].str.startswith(("6", "3", "0")) & ~df["name"].str.contains(r"ST|\*", na=False)
            return df[mask]
    except Exception as e:
        logger.warning(f"[AKShare] 获取股票列表失败: {e}")
    return pd.DataFrame()


def get_all_stocks_baostock() -> pd.DataFrame:
    """从 Baostock 获取 A 股股票列表"""
    if not BAOSTOCK_OK:
        return pd.DataFrame()
    try:
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning(f"[Baostock] 登录失败: {lg.error_msg}")
            return pd.DataFrame()
        try:
            rs = bs.query_all_stock('2026-01-01')
            rows = []
            while rs.next():
                row = rs.get_row_data()
                code = row[0]
                name = row[2]
                if code.startswith(("sh.6", "sh.68", "sz.3", "sz.0")) and "ST" not in name and "*" not in name:
                    # 统一为去掉前缀的代码
                    clean_code = code[3:]  # "sh.000001" -> "000001"
                    rows.append({"code": clean_code, "name": name, "raw_code": code})
            df = pd.DataFrame(rows)
            return df
        finally:
            bs.logout()
    except Exception as e:
        logger.warning(f"[Baostock] 获取股票列表失败: {e}")
    return pd.DataFrame()


def get_all_stocks_local() -> pd.DataFrame:
    """从本地 all_stock_info 表获取股票列表（离线兜底）"""
    try:
        conn = _get_conn()
        cursor = conn.execute("SELECT symbol, name FROM all_stock_info ORDER BY symbol")
        rows = cursor.fetchall()
        conn.close()
        if rows:
            df = pd.DataFrame(rows, columns=["code", "name"])
            logger.info(f"  从本地 all_stock_info 获取股票列表: {len(df)} 只")
            return df
    except Exception as e:
        logger.warning(f"[Local] 读取 all_stock_info 失败: {e}")
    return pd.DataFrame()


def get_all_stocks() -> pd.DataFrame:
    """综合获取股票列表，AKShare 优先，本地兜底"""
    df = get_all_stocks_akshare()
    if not df.empty:
        return df
    df = get_all_stocks_baostock()
    if not df.empty:
        return df
    df = get_all_stocks_local()
    if not df.empty:
        return df
    logger.error("无法获取股票列表（AKShare、Baostock、本地均失败）")
    return pd.DataFrame()


# ──────────────────────────────────────────
# 缓存查询
# ──────────────────────────────────────────
def get_cached_latest(symbol: str, period_key: str) -> str | None:
    """查缓存中该股票+周期的最近日期，返回 'YYYY-MM-DD' 或 None
    - 日线（daily）→ 查 baostock source
    - 分钟线（15min/30min/60min）→ 查 akshare source
    """
    if period_key == "daily":
        source = "baostock"
    elif period_key.endswith("min"):
        source = "akshare"
    else:
        return None
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND source=? AND period=?",
            (symbol, source, period_key)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0][:10]
        return None
    finally:
        conn.close()


# ──────────────────────────────────────────
# 日线：Baostock 获取
# ──────────────────────────────────────────
def _ensure_bs_connected():
    """确保 baostock 连接可用"""
    global _BS_CONNECTED
    if not BAOSTOCK_OK:
        return False
    if not _BS_CONNECTED:
        lg = bs.login()
        if lg.error_code == "0":
            _BS_CONNECTED = True
        else:
            logger.warning(f"[Baostock] 登录失败: {lg.error_msg}")
            return False
    return True


def _bs_disconnect():
    """断开 baostock 连接"""
    global _BS_CONNECTED
    if BAOSTOCK_OK and _BS_CONNECTED:
        try:
            bs.logout()
        except:
            pass
        _BS_CONNECTED = False


def fetch_daily_baostock(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """通过 baostock 获取日线数据（使用已有连接）
    返回: DataFrame=成功, None=查询失败
    """
    if not _ensure_bs_connected():
        return None
    # baostock 代码格式: sh.600000, sz.000001
    prefix = "sh" if symbol.startswith("6") or symbol.startswith("68") else "sz"
    bs_code = f"{prefix}.{symbol}"
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"
        )
        if rs.error_code != "0":
            logger.debug(f"[Baostock] {symbol} 查询失败: {rs.error_code}")
            return None
        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0] and row[1] != "":
                rows.append({
                    "trade_date": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]) if row[5] else 0,
                    "amount": float(row[6]) if row[6] else 0,
                })
        if rows:
            return pd.DataFrame(rows)
    except Exception as e:
        logger.debug(f"[Baostock] {symbol} 日线获取失败: {e}")
    return None


# ──────────────────────────────────────────
# 日线 + 分钟线：增量更新
# ──────────────────────────────────────────
def _fmt_date(d: str) -> str:
    """统一日期格式为 YYYY-MM-DD"""
    d = d.strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d[:10]


def update_daily(symbol: str, start_date: str, end_date: str) -> bool:
    """增量更新日线：先 baostock，失败后尝试 AKShare"""
    start_dt = _fmt_date(start_date)
    end_dt = _fmt_date(end_date)

    # 先看缓存最新日期
    latest = get_cached_latest(symbol, "daily")
    if latest and latest >= end_dt:
        return True  # 已最新

    # 尝试 baostock
    bs_start = latest if latest else start_dt
    sd = datetime.strptime(bs_start, "%Y-%m-%d") + timedelta(days=1)
    sd_str = sd.strftime("%Y-%m-%d")
    if sd_str > end_dt:
        return True

    df = fetch_daily_baostock(symbol, sd_str, end_dt)
    if df is not None:
        if df.empty:
            return True  # 无新数据（周末/节假日），视为最新
        if latest:
            df = df[df["trade_date"] > latest]
        if not df.empty:
            save_kline(symbol, "baostock", df, period="daily")
        return None  # 新增成功

    # baostock 无数据 → 跳过（akshare 日线不再写入 kline_cache，下次 baostock 重试即可）
    return True


def update_minute(symbol: str, period: str, start_date: str, end_date: str) -> bool:
    """增量更新分钟线（仅 AKShare）"""
    if not AKSHARE_OK:
        return True  # 无 AKShare，跳过分钟线

    period_key = f"{period}min"
    latest = get_cached_latest(symbol, period_key)
    end_dt = _fmt_date(end_date)
    if latest and latest[:10] >= end_dt:
        return True

    fetch_start = _fmt_date(start_date)
    if latest:
        latest_dt = datetime.strptime(latest[:10], "%Y-%m-%d")
        fetch_start = (latest_dt + timedelta(days=1)).strftime("%Y%m%d")
        if _fmt_date(fetch_start) > end_dt:
            return True
    else:
        fetch_start = start_date

    try:
        time.sleep(INTER_STOCK)
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol, period=period,
            start_date=fetch_start, end_date=end_date
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "时间": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            df["trade_date"] = df["trade_date"].astype(str)
            if latest:
                df = df[df["trade_date"] > latest]
            if not df.empty:
                save_kline(symbol, "akshare", df, period=period_key)
        return True
    except Exception as e:
        logger.debug(f"[AKShare] {symbol} {period}min 增量更新失败: {e}")
        return False  # 分钟线失败不影响整体


# ──────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────
def main(mode="all"):
    """
    增量数据更新
    mode: "daily" → 只更新日线
          "minute" → 只更新分钟线
          "all" → 日线+分钟线（默认）
    """
    # 设置 socket 超时（60s），baostock 偶有慢查询
    socket.setdefaulttimeout(60)

    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    logger.info(f"🚀 开始增量数据更新（mode={mode}, 30交易日）...")
    logger.info(f"  数据源: baostock={'✅' if BAOSTOCK_OK else '❌'}  akshare={'✅' if AKSHARE_OK else '❌'}")

    now = datetime.now()
    # 盘前/盘中（< 17:00）不请求今日数据，统一用昨天
    if now.hour < 17:
        end = now - timedelta(days=1)
    else:
        end = now
    # 如果 end 落在周末，回退到上周五
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    end_date = end.strftime("%Y%m%d")
    start_date = (end - timedelta(days=FETCH_DAYS_DAILY)).strftime("%Y%m%d")
    logger.info(f"  时间范围: {start_date} ~ {end_date}  (当前{now.hour}:{now.minute:02d}, 使用日期: {end_date})")

    stocks = get_all_stocks()
    if stocks.empty:
        logger.error("无法获取股票列表，终止更新")
        return

    total = len(stocks)
    logger.info(f"  共 {total} 只股票")

    # --- 日线（baostock + AKShare fallback）---
    if mode in ("all", "daily"):
        logger.info("--- 日线更新 ---")
        d_ok = d_skip = d_fail = d_consec = 0
        for idx, (_, row) in enumerate(stocks.iterrows()):
            code = row["code"]
            ok = update_daily(code, start_date, end_date)
            if ok is True:
                d_skip += 1
                d_consec = 0
            elif ok is None:
                d_ok += 1
                d_consec = 0
            else:
                d_fail += 1
                d_consec += 1
                if d_consec >= 200:
                    # 连续失败太多，可能 API 挂了，直接跳过后续
                    logger.warning(f"  连续失败 {d_consec} 次，跳过剩余日线更新")
                    break
            if (idx + 1) % BATCH_SIZE == 0:
                logger.info(f"  日线: {idx+1}/{total} (最新{d_skip}, 新增{d_ok}, 失败{d_fail}), 休息 {INTER_BATCH}s...")
                # 定期 WAL checkpoint 防止 WAL 文件膨胀
                conn = _get_conn()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()
                time.sleep(INTER_BATCH)
        logger.info(f"  日线完成: 最新{d_skip}, 新增{d_ok}, 失败{d_fail}/{total}")
    else:
        logger.info("--- 跳过日线更新 ---")

    # --- 分钟线（仅 AKShare）---
    if mode in ("all", "minute"):
        if AKSHARE_OK:
            for minute_period in ("15", "30", "60"):
                logger.info(f"--- {minute_period}min 分钟线更新 ---")
                m_skip = m_ok = m_fail = 0
                for idx, (_, row) in enumerate(stocks.iterrows()):
                    code = row["code"]
                    ok = update_minute(code, minute_period, start_date, end_date)
                    if ok is True:
                        m_skip += 1
                    else:
                        m_fail += 1
                    if (idx + 1) % BATCH_SIZE == 0:
                        logger.info(f"  {minute_period}min: {idx+1}/{total} (最新{m_skip}, 失败{m_fail}), 休息 {INTER_BATCH}s...")
                        # 定期 WAL checkpoint
                        conn = _get_conn()
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.close()
                        time.sleep(INTER_BATCH)
                    if m_fail >= BATCH_SIZE:
                        logger.warning(f"  {minute_period}min 连续失败 {m_fail} 次，跳过")
                        break
                logger.info(f"  {minute_period}min 完成: 最新{m_skip}, 失败{m_fail}/{total}")
        else:
            logger.info("--- 分钟线: AKShare 不可用，跳过 ---")
    else:
        logger.info("--- 跳过分钟线更新 ---")

    _bs_disconnect()

    # --- CR 指标计算（仅日线更新后） ---
    if mode in ("all", "daily"):
        logger.info("--- CR指标计算 ---")
        try:
            from scripts.calc_cr_indicator import run_all
            run_all()
        except Exception as e:
            logger.warning(f"⚠ CR指标计算失败: {e}")

    logger.info(f"✅ 数据更新完成 (mode={mode})")


if __name__ == "__main__":
    import sys
    mode = "all"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]
    main(mode=mode)
