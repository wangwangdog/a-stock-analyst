#!/usr/bin/env python3
"""tencent_fq 日线增量更新：盘后运行，补齐当日数据。
双源校验：腾讯主 + Baostock 兜底。
- 数据差<10% → 腾讯为准
- 数据差>20% → 对比前一日，选更接近的
- 腾讯缺 amount → Baostock 补"""
import sys, os, json, urllib.request, sqlite3, time, logging
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DB_PATH = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")
ROOT = Path(__file__).resolve().parent.parent.parent
MAX_WORKERS = 8
SKIP_WEEKEND = True
DIFF_THRESHOLD = 10   # %，以内用腾讯
DIVERGE_THRESHOLD = 20  # %，以上要对比前一日

# ── Baostock 状态 ──
_BS_LOGGED_IN = False


def _ensure_bs_login():
    global _BS_LOGGED_IN
    if _BS_LOGGED_IN:
        return True
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            _BS_LOGGED_IN = True
            return True
        log.warning(f"baostock 登录失败: {lg.error_msg}")
        return False
    except Exception as e:
        log.warning(f"baostock 登录异常: {e}")
        return False


def _bs_logout():
    global _BS_LOGGED_IN
    if _BS_LOGGED_IN:
        try:
            import baostock as bs
            bs.logout()
        except Exception:
            pass
        _BS_LOGGED_IN = False


def _to_bs_code(sym: str) -> str:
    mkt, code = sym.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt, "sh")
    return f"{prefix}.{code}"


# ── 腾讯 HTTP ──

def tencent_code(symbol: str) -> str:
    mkt, code = symbol.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt, mkt.lower())
    return f"{prefix}{code}"


def fetch_tencent(tc: str) -> dict | None:
    """返回 {date: {open,close,high,low,volume(手),amount}}"""
    url = f"http://ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,,,5,qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        sd = data.get("data", {}).get(tc, {})
        days = sd.get("qfqday", sd.get("day", sd.get("hfqday", [])))
        if not days:
            return None
        result = {}
        for item in days:
            if len(item) < 6:
                continue
            ds = item[0]
            if len(ds) != 10:
                continue
            try:
                vol = float(item[5]) if isinstance(item[5], (str, int, float)) else 0
                amt = float(item[6]) if len(item) > 6 and isinstance(item[6], (str, int, float)) else 0
                result[ds] = {
                    "open": float(item[1]), "close": float(item[2]),
                    "high": float(item[3]), "low": float(item[4]),
                    "volume": vol, "amount": amt,
                }
            except (ValueError, IndexError):
                continue
        return result if result else None
    except Exception:
        return None


# ── Baostock ──

def fetch_baostock(sym: str, target_date: str) -> dict | None:
    """返回 {date: {open,close,high,low,volume(手),amount}}
    Baostock volume 原始为股，÷100 存手。"""
    if not _ensure_bs_login():
        return None
    try:
        import baostock as bs
        bs_code = _to_bs_code(sym)
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=target_date, end_date=target_date,
            frequency="d", adjustflag="2",
        )
        if rs.error_code != "0":
            return None
        while rs.next():
            row = rs.get_row_data()
            if row[0] != target_date:
                continue
            try:
                vol = float(row[5]) / 100 if row[5] else 0   # 股→手
                amt = float(row[6]) if row[6] else 0
                return {
                    target_date: {
                        "open": float(row[1] or 0),
                        "close": float(row[4] or 0),
                        "high": float(row[2] or 0),
                        "low": float(row[3] or 0),
                        "volume": vol,
                        "amount": amt,
                    }
                }
            except (ValueError, TypeError):
                return None
        return None
    except Exception:
        return None


# ── 前一日数据 ──

def get_prev_close(sym: str, today_str: str) -> float | None:
    """从 kline_cache 取最近一个交易日的 close"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout=10000")
        r = conn.execute(
            "SELECT close FROM kline_cache "
            "WHERE symbol=? AND source='tencent_fq' AND period='daily' AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 1",
            (sym, today_str)
        ).fetchone()
        conn.close()
        return r[0] if r else None
    except Exception:
        return None


# ── 双源校验合并 ──

def _pct_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 0.01)
    return abs(a - b) / denom * 100


def merge_bars(t_bar: dict | None, b_bar: dict | None, prev_close: float | None) -> dict | None:
    """双源校验合并，返回最终 bar"""
    if t_bar and b_bar:
        close_diff = _pct_diff(t_bar["close"], b_bar["close"])
        vol_diff = _pct_diff(t_bar["volume"], b_bar["volume"])

        if max(close_diff, vol_diff) < DIFF_THRESHOLD:
            # 数据一致 → 腾讯为准，补 amount
            bar = dict(t_bar)
            if bar["amount"] == 0 and b_bar["amount"] > 0:
                bar["amount"] = b_bar["amount"]
            return bar

        if max(close_diff, vol_diff) >= DIVERGE_THRESHOLD and prev_close is not None:
            # 差异过大 → 对比前一日
            t_dev = _pct_diff(t_bar["close"], prev_close)
            b_dev = _pct_diff(b_bar["close"], prev_close)
            bar = dict(t_bar) if t_dev <= b_dev else dict(b_bar)
            if bar["amount"] == 0 and (t_bar if t_dev <= b_dev else b_bar)["amount"] > 0:
                pass  # 以选定源的 amount 为准
            return bar

        # 10%~20% 之间，仍以腾讯为准
        bar = dict(t_bar)
        if bar["amount"] == 0 and b_bar["amount"] > 0:
            bar["amount"] = b_bar["amount"]
        return bar

    if t_bar:
        return dict(t_bar)
    if b_bar:
        return dict(b_bar)
    return None


# ── 写库 ──

def _write_bars(c, sym, bars, today_str):
    new = 0
    for ds, b in bars.items():
        if ds < today_str:
            continue
        try:
            c.execute(
                "INSERT OR IGNORE INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)",
                (sym, ds, b["open"], b["close"], b["high"], b["low"], b["volume"], b["amount"]),
            )
            if c.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except Exception:
            pass
    return new


# ══════════════════════════════════════════════

def main():
    t0 = time.time()
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    if SKIP_WEEKEND and today.weekday() >= 5:
        log.info("非交易日，跳过")
        return

    # 登录 baostock（全局一次性登录）
    if not _ensure_bs_login():
        log.warning("baostock 不可用，仅用腾讯源")
    has_bs = _BS_LOGGED_IN

    # 获取待更新股票列表
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=30000")
    stocks = conn.execute(
        "SELECT symbol, MAX(trade_date) FROM kline_cache "
        "WHERE source='tencent_fq' AND period='daily' AND symbol LIKE '%.%' "
        "GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    conn.close()

    to_update = []
    for sym, last_dt in stocks:
        if not last_dt or last_dt < today_str:
            to_update.append(sym)

    if not to_update:
        log.info("所有股票已是最新，无需更新")
        return

    log.info("需要更新 %d 只股票（共 %d 只）%s",
             len(to_update), len(stocks), "+baostock" if has_bs else "")

    total_new = 0
    total_bs_fallback = 0  # baostock 被选中
    total_tc_fallback = 0  # baostock 补 amount
    total_err = 0
    done = 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=30000")

    def process_one(sym):
        nonlocal total_new, total_bs_fallback, total_tc_fallback, total_err

        tc = tencent_code(sym)
        t_bars = fetch_tencent(tc)
        b_bars = fetch_baostock(sym, today_str) if has_bs else None

        # 前一日收盘价
        prev_close = get_prev_close(sym, today_str)

        # 合并校验
        bar = merge_bars(
            (t_bars or {}).get(today_str),
            (b_bars or {}).get(today_str),
            prev_close,
        )

        if not bar:
            return (sym, 0, "双源均无数据")

        # 统计兜底来源
        if b_bars and today_str in b_bars:
            if t_bars and today_str in t_bars:
                t = t_bars[today_str]
                b = b_bars[today_str]
                if max(_pct_diff(t["close"], b["close"]), _pct_diff(t["volume"], b["volume"])) >= DIVERGE_THRESHOLD:
                    total_bs_fallback += 1
            else:
                total_bs_fallback += 1  # 腾讯无数据，baostock顶上
        if bar["amount"] == 0 and b_bars and today_str in b_bars and b_bars[today_str]["amount"] > 0:
            pass  # 已在 merge_bars 中补过

        new = 0
        try:
            c = sqlite3.connect(DB_PATH)
            c.execute("PRAGMA busy_timeout=30000")
            new = _write_bars(c, sym, {today_str: bar}, today_str)
            c.commit()
            c.close()
            return (sym, new, "ok")
        except Exception as e:
            return (sym, 0, str(e))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process_one, s): s for s in to_update}
        for f in as_completed(futures):
            done += 1
            sym, new, err = f.result()
            if new:
                total_new += new
            if err != "ok":
                total_err += 1
            if done % 1000 == 0 or done == len(to_update):
                elapsed = time.time() - t0
                log.info("[%d/%d] 新增%d条, bs顶替%d, 错误%d, %.0fs",
                         done, len(to_update), total_new, total_bs_fallback, total_err, elapsed)

    # 清理当天残留的非 tencent_fq 数据
    try:
        c = sqlite3.connect(DB_PATH)
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("DELETE FROM kline_cache WHERE period='daily' AND source!='tencent_fq' AND trade_date=?",
                  (today_str,))
        c.commit()
        c.close()
    except Exception:
        pass

    _bs_logout()
    elapsed = time.time() - t0
    log.info("完成! %.0fs, 处理%d只, 新增%d条, bs顶替%d, 错误%d",
             elapsed, done, total_new, total_bs_fallback, total_err)


if __name__ == "__main__":
    main()
