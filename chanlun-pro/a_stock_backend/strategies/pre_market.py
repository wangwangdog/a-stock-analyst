"""
盘前策略引擎 (增强完整版)
在 08:00-09:15 执行：

采集流程:
1. AKShare 采集昨日涨停池 stock_zt_pool_em + 跌停池 stock_zt_pool_dtgc_em
2. 连板数统计、封单额提取
3. 概念板块采集 stock_board_concept_name_em + 个股映射 stock_board_concept_cons_em
4. 全市场日线动量计算（涨幅TOP排名，从 stock_daily 表读取）
5. 关注池 1分钟K线下载（前5个交易日）
6. 生成综合报告文本

数据表依赖:
  stock_daily, zt_pool, zt_pool_dt, stock_concepts, stock_concept_map,
  stock_kline_1min, favorites, cl_zixuan_watchlist, vol20day, trade_calendar
"""
import logging
import sqlite3
import os
import sys
import time
import random
import socket
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pre_market")

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

AKSHARE_TIMEOUT = 45
AKSHARE_RETRIES = 3


# ── Helpers ────────────────────────────────────────────────────────

def _get_conn():
    return sqlite3.connect(DB_PATH)


def _force_ipv4():
    """强制 socket 走 IPv4（避免 AKShare IPv6 被拒）"""
    orig = socket.getaddrinfo
    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _ipv4


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_date_compact(d: date) -> str:
    return d.strftime("%Y%m%d")


def _get_watchlist_symbols(conn) -> list:
    """从 cl_zixuan_watchlist + favorites 收集关注池股票代码（去重）"""
    symbols = set()
    # cl_zixuan_watchlist 格式: 'SZ.002579', 'SH.000001'
    try:
        rows = conn.execute("SELECT stock_code FROM cl_zixuan_watchlist").fetchall()
        for (code,) in rows:
            code = code.strip()
            # 去掉前缀 SZ./SH.，只保留纯数字
            if "." in code:
                code = code.split(".")[1]
            if code.isdigit():
                symbols.add(code.zfill(6))
    except Exception:
        pass
    # favorites 表: symbol 直接存代码
    try:
        rows = conn.execute("SELECT symbol FROM favorites").fetchall()
        for (code,) in rows:
            code = code.strip()
            if code.isdigit():
                symbols.add(code.zfill(6))
    except Exception:
        pass
    # 兜底默认
    if not symbols:
        symbols = {"000001", "600519", "000858", "300124"}
    return sorted(symbols)


def _get_last_trading_days(conn, n: int = 5) -> list:
    """获取最近 n 个交易日（从 trade_calendar 或 stock_daily 推算）"""
    try:
        rows = conn.execute(
            "SELECT calendar_date FROM trade_calendar "
            "WHERE is_trading_day=1 AND calendar_date <= ? "
            "ORDER BY calendar_date DESC LIMIT ?",
            (_fmt_date(date.today()), n),
        ).fetchall()
        if len(rows) >= n:
            return [r[0] for r in rows]
    except Exception:
        pass
    # 降级：从 stock_daily 取
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM stock_daily "
            "ORDER BY date DESC LIMIT ?",
            (n + 5,),
        ).fetchall()
        return [r[0] for r in rows[:n]]
    except Exception:
        return [(_fmt_date(date.today() - timedelta(i))) for i in range(1, n + 1)]


# ── 1. 涨停/跌停池采集 ────────────────────────────────────────────

def collect_zt_pools(target_date: Optional[str] = None) -> dict:
    """采集指定日期的涨停池 + 跌停池

    Args:
        target_date: YYYYMMDD 格式，默认为昨日

    Returns:
        {"zt_count": int, "dt_count": int, "zt_symbols": [...], "dt_symbols": [...]}
    """
    if target_date is None:
        target_date = _fmt_date_compact(date.today() - timedelta(1))

    _force_ipv4()
    result = {"zt_count": 0, "dt_count": 0, "zt_symbols": [], "dt_symbols": []}

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare 未安装，跳过涨停/跌停池采集")
        return result

    conn = _get_conn()
    try:
        # ── 涨停池 stock_zt_pool_em ──
        zt_date = _fmt_date(date.today() - timedelta(1))
        df = None
        for attempt in range(AKSHARE_RETRIES):
            try:
                logger.info(f"📡 采集涨停池 (attempt {attempt+1}): {target_date}")
                df = ak.stock_zt_pool_em(date=target_date)
                break
            except Exception as e:
                logger.warning(f"  涨停池请求失败: {e}")
                if attempt < AKSHARE_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
        if df is None:
            raise RuntimeError("涨停池采集全部重试失败")

        zt_count = 0
        for _, row in df.iterrows():
            symbol = str(row.get("代码", "")).strip().zfill(6)
            if not symbol or not symbol.isdigit():
                continue
            name = str(row.get("名称", ""))
            close_price = _safe_float(row.get("最新价", 0))
            fd_amount = _safe_float(row.get("封板资金", 0))   # 封单额
            lb_count = _safe_int(row.get("连板数", 0))         # 连板数
            industry = str(row.get("所属行业", ""))
            zt_stats = str(row.get("涨停统计", ""))            # 如 "1/1"
            zb_times = _safe_int(row.get("炸板次数", 0))       # 炸板次数
            is_zb = 1 if zb_times > 0 else 0

            conn.execute(
                """INSERT OR REPLACE INTO zt_pool
                   (date, symbol, name, close_price, zt_price, fd_amount, lb_count, concept, is_zb)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (zt_date, symbol, name, close_price, 0.0,
                 fd_amount, lb_count, industry, is_zb),
            )
            zt_count += 1
            result["zt_symbols"].append(symbol)

        conn.commit()
        logger.info(f"✅ 涨停池写入 {zt_count} 条")
        result["zt_count"] = zt_count

        # ── 跌停池 stock_zt_pool_dtgc_em ──
        df_dt = None
        for attempt in range(AKSHARE_RETRIES):
            try:
                logger.info(f"📡 采集跌停池 (attempt {attempt+1}): {target_date}")
                df_dt = ak.stock_zt_pool_dtgc_em(date=target_date)
                break
            except Exception as e:
                logger.warning(f"  跌停池请求失败: {e}")
                if attempt < AKSHARE_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
        if df_dt is None:
            raise RuntimeError("跌停池采集全部重试失败")

        dt_count = 0
        for _, row in df_dt.iterrows():
            symbol = str(row.get("代码", "")).strip().zfill(6)
            if not symbol or not symbol.isdigit():
                continue
            name = str(row.get("名称", ""))
            close_price = _safe_float(row.get("最新价", 0))
            dt_fd = _safe_float(row.get("封单资金", 0))        # 跌停封单
            continuous_dt = _safe_int(row.get("连续跌停", 0))  # 连续跌停天数

            conn.execute(
                """INSERT OR REPLACE INTO zt_pool_dt
                   (date, symbol, name, close_price, dt_price)
                   VALUES (?, ?, ?, ?, ?)""",
                (zt_date, symbol, name, close_price, dt_fd),
            )
            dt_count += 1
            result["dt_symbols"].append(symbol)

        conn.commit()
        logger.info(f"✅ 跌停池写入 {dt_count} 条")
        result["dt_count"] = dt_count

    except Exception as e:
        logger.error(f"涨停/跌停池采集异常: {e}", exc_info=True)
    finally:
        conn.close()

    return result


# ── 2. 连板数与封单额统计 ─────────────────────────────────────────

def analyze_limitup_stats(conn, trade_date: str) -> dict:
    """从 zt_pool 表统计连板分布、封单额排名等

    Returns:
        {
            "lb_distribution": {1: 10, 2: 5, ...},  # 连板数 -> 数量
            "top_fd": [{"symbol":..., "name":..., "fd_amount":..., "lb_count":...}, ...],
            "total_zt": int,
        }
    """
    rows = conn.execute(
        """SELECT symbol, name, fd_amount, lb_count, concept
           FROM zt_pool WHERE date = ? AND lb_count > 0
           ORDER BY lb_count DESC, fd_amount DESC""",
        (trade_date,),
    ).fetchall()

    lb_dist = {}
    top_fd = []
    for r in rows:
        symbol, name, fd, lb, concept = r
        lb_dist[lb] = lb_dist.get(lb, 0) + 1
        top_fd.append({
            "symbol": symbol,
            "name": name,
            "fd_amount": fd or 0,
            "lb_count": lb or 0,
            "concept": concept or "",
        })

    return {
        "lb_distribution": dict(sorted(lb_dist.items(), reverse=True)),
        "top_fd": top_fd[:20],  # 封单额 TOP20
        "total_zt": len(rows),
    }


# ── 3. 概念板块采集 ────────────────────────────────────────────────

def collect_concepts(timeout: int = 60) -> dict:
    """采集全市场概念板块 + 个股映射

    Returns:
        {"concepts_count": int, "mapping_count": int}
    """
    _force_ipv4()
    result = {"concepts_count": 0, "mapping_count": 0}

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare 未安装，跳过概念板块采集")
        return result

    conn = _get_conn()
    try:
        total_maps = 0

        # ── 概念板块列表 ──
        df = None
        for attempt in range(AKSHARE_RETRIES):
            try:
                logger.info("📡 采集概念板块列表")
                df = ak.stock_board_concept_name_em()
                break
            except Exception as e:
                logger.warning(f"  概念板块列表请求失败: {e}")
                if attempt < AKSHARE_RETRIES - 1:
                    time.sleep(3 ** attempt)
                else:
                    raise
        if df is None:
            raise RuntimeError("概念板块列表采集全部重试失败")

        con_count = 0
        concept_pairs = []  # (code, name) pairs
        for _, row in df.iterrows():
            code = str(row.get("板块代码", "")).strip()
            name = str(row.get("板块名称", "")).strip()
            if code and name:
                conn.execute(
                    "INSERT OR REPLACE INTO stock_concepts (code, name, category) VALUES (?, ?, 'concept')",
                    (code, name),
                )
                con_count += 1
                concept_pairs.append((code, name))

        conn.commit()
        logger.info(f"✅ 概念板块: {con_count} 个")
        result["concepts_count"] = con_count

        # ── 个股概念映射（取前 100 个板块，避免请求过多）──
        limit = min(100, len(concept_pairs))
        logger.info(f"📡 采集个股概念映射 (共 {limit} 个板块)")
        for i, (ccode, cname) in enumerate(concept_pairs[:limit]):
            if i > 0 and i % 10 == 0:
                time.sleep(random.uniform(0.5, 1.5))  # 礼貌间隔
            try:
                cons = ak.stock_board_concept_cons_em(symbol=cname)
                for _, c in cons.iterrows():
                    sym = str(c.get("代码", "")).strip().zfill(6)
                    cn = str(c.get("名称", ""))
                    if sym and sym.isdigit():
                        conn.execute(
                            "INSERT OR REPLACE INTO stock_concept_map (symbol, name, concept_code, concept_name) VALUES (?, ?, ?, ?)",
                            (sym, cn, ccode, cname),
                        )
                        total_maps += 1
                if (i + 1) % 20 == 0:
                    conn.commit()
                    logger.info(f"  ... {i+1}/{limit} 板块, 已映射 {total_maps} 条")
            except Exception as e:
                logger.warning(f"  概念 '{cname}' 映射失败: {e}")
                continue

        conn.commit()
        logger.info(f"✅ 个股概念映射: {total_maps} 条")
        result["mapping_count"] = total_maps

    except Exception as e:
        logger.error(f"概念板块采集异常: {e}", exc_info=True)
    finally:
        conn.close()

    return result


# ── 4. 全市场日线动量计算 ─────────────────────────────────────────

def calc_momentum_ranking(conn, trade_date: str, top_n: int = 100) -> list:
    """从 stock_daily 表计算全市场日线动量（涨幅排名）

    计算方法：
    - 当日涨跌幅 = (close / pre_close - 1) * 100
    - 若 pre_close 缺失则跳过
    - 返回 TOP N

    Returns:
        [{"symbol":..., "name":..., "pct_chg":..., "close":..., "volume":..., "turnover":...}, ...]
    """
    rows = conn.execute(
        """WITH priced AS (
            SELECT symbol, close, volume, turnover,
                   LAG(close, 1) OVER (PARTITION BY symbol ORDER BY date) AS pre_close
            FROM stock_daily
            WHERE date = ?
        )
        SELECT symbol, close, volume, turnover, pre_close
        FROM priced
        WHERE close > 0 AND pre_close > 0
        ORDER BY (close - pre_close) / pre_close DESC
        LIMIT ?""",
        (trade_date, top_n),
    ).fetchall()

    # 补名称（从 all_stock_info 或 zt_pool）
    name_cache = {}
    try:
        for (sym, name) in conn.execute("SELECT symbol, name FROM all_stock_info"):
            name_cache[sym] = name
    except Exception:
        pass

    result = []
    for r in rows:
        symbol, close, volume, turnover, pre_close = r
        pct = round((close / pre_close - 1) * 100, 2)
        name = name_cache.get(symbol, "")
        result.append({
            "symbol": symbol,
            "name": name,
            "pct_chg": pct,
            "close": close,
            "volume": int(volume) if volume else 0,
            "turnover": turnover or 0,
        })

    return result


# ── 5. 关注池1分钟K线下载 ────────────────────────────────────────

def download_watchlist_1min_klines(days_back: int = 5) -> dict:
    """下载关注池股票的 1分钟K线（前 N 个交易日）

    Returns:
        {"downloaded": int, "failed": int, "symbols": [...], "total_bars": int}
    """
    _force_ipv4()
    result = {"downloaded": 0, "failed": 0, "symbols": [], "total_bars": 0}

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare 未安装，跳过 1分钟K线下载")
        return result

    conn = _get_conn()
    try:
        # 获取关注池
        symbols = _get_watchlist_symbols(conn)
        # 获取交易日
        trading_days = _get_last_trading_days(conn, n=days_back)
        if not trading_days:
            logger.warning("没有交易日数据，使用最近日期")
            trading_days = [_fmt_date(date.today() - timedelta(i)) for i in range(days_back, 0, -1)]

        start_date_str = trading_days[0] + " 09:25:00"
        end_date_str = trading_days[-1] + " 15:05:00"

        logger.info(f"📡 下载 {len(symbols)} 只关注股 1分钟K线 ({trading_days[0]} ~ {trading_days[-1]})")

        total_bars = 0
        downloaded = 0
        failed = 0

        for i, symbol in enumerate(symbols):
            if i > 0 and i % 5 == 0:
                time.sleep(random.uniform(0.3, 0.8))  # 礼貌间隔

            try:
                df = ak.stock_zh_a_hist_min_em(
                    symbol=symbol,
                    period="1",
                    start_date=start_date_str,
                    end_date=end_date_str,
                    adjust="",
                )
                if df is None or df.empty:
                    failed += 1
                    continue

                bar_count = 0
                for _, row in df.iterrows():
                    dt_str = str(row.get("时间", ""))
                    if not dt_str:
                        continue
                    # 解析时间: "2026-06-08 09:31:00" -> trade_date="2026-06-08"
                    try:
                        dt_parsed = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        try:
                            dt_parsed = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                        except ValueError:
                            continue
                    trade_date = dt_parsed.strftime("%Y-%m-%d")
                    o = _safe_float(row.get("开盘", 0))
                    c = _safe_float(row.get("收盘", 0))
                    h = _safe_float(row.get("最高", 0))
                    l = _safe_float(row.get("最低", 0))
                    v = _safe_float(row.get("成交量", 0))
                    a = _safe_float(row.get("成交额", 0))

                    conn.execute(
                        """INSERT OR REPLACE INTO stock_kline_1min
                           (symbol, trade_date, open, close, high, low, volume, amount, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                        (symbol, trade_date, o, c, h, l, v, a),
                    )
                    bar_count += 1

                if bar_count > 0:
                    total_bars += bar_count
                    downloaded += 1
                    result["symbols"].append(symbol)
                    if (i + 1) % 10 == 0:
                        conn.commit()
                        logger.info(f"  ... {i+1}/{len(symbols)} 只, 共 {total_bars} 根K线")
                else:
                    failed += 1

            except Exception as e:
                logger.warning(f"  ❌ {symbol} 1min下载失败: {e}")
                failed += 1
                continue

        conn.commit()
        result["downloaded"] = downloaded
        result["failed"] = failed
        result["total_bars"] = total_bars
        logger.info(f"✅ 1分钟K线: {downloaded} 只成功, {failed} 只失败, 共 {total_bars} 根K线")

    except Exception as e:
        logger.error(f"1分钟K线下载异常: {e}", exc_info=True)
    finally:
        conn.close()

    return result


# ── 6. 报告生成 ───────────────────────────────────────────────────

def generate_report(
    trade_date: str,
    zt_result: dict,
    lb_stats: dict,
    momentum: list,
    concept_result: dict,
    kline_result: dict,
) -> str:
    """生成综合盘前策略报告文本"""
    lines = []
    lines.append(f"📅 **盘前策略报告 — {trade_date}**")
    lines.append("=" * 40)

    # ── 涨停/跌停概览 ──
    lines.append("\n## 1️⃣ 涨停/跌停情绪")
    lines.append(f"- 涨停家数: **{zt_result.get('zt_count', 0)}** 只")
    lines.append(f"- 跌停家数: **{zt_result.get('dt_count', 0)}** 只")
    if zt_result.get("dt_symbols"):
        dt_list = zt_result["dt_symbols"][:10]
        lines.append(f"  - 跌停股(前10): {', '.join(dt_list)}")

    # ── 连板统计 ──
    lines.append("\n## 2️⃣ 连板统计")
    lines.append(f"- 涨停总数(含连板): **{lb_stats.get('total_zt', 0)}** 只")
    lb_dist = lb_stats.get("lb_distribution", {})
    if lb_dist:
        for lb, cnt in lb_dist.items():
            lines.append(f"  - {lb}连板: {cnt} 只")
    lines.append("")
    top_fd = lb_stats.get("top_fd", [])
    if top_fd:
        lines.append("**封单额 TOP 5:**")
        for i, s in enumerate(top_fd[:5], 1):
            sym = s["symbol"]
            name = s.get("name", "")
            fd = s.get("fd_amount", 0)
            lb = s.get("lb_count", 0)
            # 格式化封单额
            if fd >= 100_000_000:
                fd_str = f"{fd/1e8:.2f}亿"
            elif fd >= 10_000:
                fd_str = f"{fd/1e4:.1f}万"
            else:
                fd_str = f"{fd:.0f}"
            concept = s.get("concept", "")
            lines.append(f"  {i}. {sym}({name}) 封单{fd_str} {lb}连板 [{concept}]")

    # ── 动量排名 ──
    lines.append("\n## 3️⃣ 全市场日线动量 TOP 10")
    if momentum:
        for i, s in enumerate(momentum[:10], 1):
            sym = s["symbol"]
            name = s.get("name", "")
            pct = s.get("pct_chg", 0)
            vol = s.get("volume", 0)
            vol_str = f"{vol/1e4:.0f}万手" if vol >= 10000 else f"{vol:.0f}手"
            lines.append(f"  {i}. **{sym}** {name}  **{pct:+.2f}%**  量{vol_str}")

    # ── 概念板块 ──
    lines.append("\n## 4️⃣ 概念板块更新")
    cc = concept_result.get("concepts_count", 0)
    mc = concept_result.get("mapping_count", 0)
    lines.append(f"- 概念板块: **{cc}** 个")
    lines.append(f"- 个股概念映射: **{mc}** 条")

    # ── 1分钟K线 ──
    lines.append("\n## 5️⃣ 关注池 1分钟K线")
    dl = kline_result.get("downloaded", 0)
    fl = kline_result.get("failed", 0)
    tb = kline_result.get("total_bars", 0)
    lines.append(f"- 成功下载: **{dl}** 只")
    lines.append(f"- 下载失败: {fl} 只" if fl else "- 下载失败: 0 只 ✅")
    lines.append(f"- 总K线数: **{tb}** 根")

    # ── 重点关注建议 ──
    lines.append("\n## 6️⃣ 今日重点关注")
    # 从连板高标 + 动量强势中筛选
    candidates = []
    # 连板高标（3板以上）
    for s in top_fd:
        if s.get("lb_count", 0) >= 3:
            candidates.append(s)

    # 动量+涨停双强
    momentum_symbols = {s["symbol"] for s in momentum[:20]}
    for s in top_fd:
        if s["symbol"] in momentum_symbols and len(candidates) < 15:
            if s not in candidates:
                candidates.append(s)

    if candidates:
        lines.append(f"**共筛选 {len(candidates)} 只重点关注股票:**")
        for i, s in enumerate(candidates[:15], 1):
            sym = s["symbol"]
            name = s.get("name", "")
            lb = s.get("lb_count", 0)
            fd = s.get("fd_amount", 0)
            fd_str = f"{fd/1e8:.2f}亿" if fd >= 1e8 else f"{fd/1e4:.0f}万"
            concept = s.get("concept", "")
            tag = "🔥" if lb >= 5 else ("⭐" if lb >= 3 else "📌")
            lines.append(f"  {tag} {sym} {name}  **{lb}连板** 封单{fd_str}  [{concept}]")
    else:
        lines.append(" 暂无符合条件的标的。")

    lines.append("\n" + "=" * 40)
    lines.append(f"🕒 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("⚠️ 本报告由 AI 辅助生成，不构成投资建议。")

    return "\n".join(lines)


# ── 7. 主入口 ──────────────────────────────────────────────────────

def run_pre_market(target_date: Optional[str] = None) -> dict:
    """执行完整盘前策略分析流水线

    Args:
        target_date: YYYYMMDD 格式，用于涨停池采集；默认为昨日

    Returns:
        {
            "status": "ok" | "error",
            "date": str,
            "zt_pool": {...},
            "concepts": {...},
            "momentum": [...],
            "lb_stats": {...},
            "kline_1min": {...},
            "report": str,
        }
    """
    today = date.today()
    yesterday = today - timedelta(1)
    trade_date = _fmt_date(yesterday)
    zt_date_compact = _fmt_date_compact(yesterday) if target_date is None else target_date

    conn = _get_conn()
    try:
        # 获取 stock_daily 最新日期
        latest_date = conn.execute(
            "SELECT MAX(date) FROM stock_daily"
        ).fetchone()[0]
        if latest_date:
            # 若有日线数据，以日线日期为准
            momentum_date = latest_date
            logger.info(f"📊 日线最新日期: {latest_date}")
        else:
            momentum_date = trade_date
    finally:
        conn.close()

    logger.info("=" * 50)
    logger.info(f"🚀 盘前策略分析启动 | 日期: {trade_date}")
    logger.info("=" * 50)

    # Step 1: 采集涨停/跌停池
    logger.info("\n[Step 1/5] 采集涨停/跌停池...")
    zt_result = collect_zt_pools(zt_date_compact)

    # Step 2: 连板统计（从 zt_pool 表读）
    logger.info("\n[Step 2/5] 连板数 & 封单额统计...")
    conn = _get_conn()
    try:
        lb_stats = analyze_limitup_stats(conn, _fmt_date(yesterday))
    finally:
        conn.close()

    # Step 3: 概念板块采集
    logger.info("\n[Step 3/5] 概念板块采集...")
    concept_result = collect_concepts()

    # Step 4: 全市场动量排名
    logger.info("\n[Step 4/5] 全市场日线动量计算...")
    conn = _get_conn()
    try:
        momentum = calc_momentum_ranking(conn, momentum_date, top_n=100)
        logger.info(f"  ✅ 动量排名: {len(momentum)} 只")
    finally:
        conn.close()

    # Step 5: 关注池 1分钟K线下载
    logger.info("\n[Step 5/5] 关注池 1分钟K线下载...")
    kline_result = download_watchlist_1min_klines(days_back=5)

    # Step 6: 生成报告
    logger.info("\n📝 生成盘前策略报告...")
    report = generate_report(
        trade_date=momentum_date,
        zt_result=zt_result,
        lb_stats=lb_stats,
        momentum=momentum,
        concept_result=concept_result,
        kline_result=kline_result,
    )

    # 汇总结果
    result = {
        "status": "ok",
        "date": momentum_date,
        "zt_pool": zt_result,
        "concepts": concept_result,
        "momentum": momentum,
        "lb_stats": lb_stats,
        "kline_1min": kline_result,
        "report": report,
    }

    logger.info("=" * 50)
    logger.info(f"✅ 盘前策略分析完成")
    logger.info(f"   涨停: {zt_result.get('zt_count', 0)} | 跌停: {zt_result.get('dt_count', 0)}")
    logger.info(f"   概念板块: {concept_result.get('concepts_count', 0)}")
    logger.info(f"   动量排名: {len(momentum)}")
    logger.info(f"   1minK线: {kline_result.get('downloaded', 0)} 只 / {kline_result.get('total_bars', 0)} 根")
    logger.info("=" * 50)

    return result


# ── CLI 入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="盘前策略引擎（增强完整版）")
    parser.add_argument("--date", type=str, help="涨停池日期 YYYYMMDD（默认昨日）")
    parser.add_argument("--zt-only", action="store_true", help="仅采集涨停/跌停池")
    parser.add_argument("--concepts-only", action="store_true", help="仅采集概念板块")
    parser.add_argument("--momentum-only", action="store_true", help="仅计算日线动量排名")
    parser.add_argument("--kline-only", action="store_true", help="仅下载1分钟K线")
    parser.add_argument("--report-only", action="store_true", help="仅生成报告（用已有数据）")
    parser.add_argument("--watch-symbols", type=str, nargs="+", help="指定1分钟K线下载的股票代码")

    args = parser.parse_args()

    if args.zt_only:
        result = collect_zt_pools(args.date)
        print(f"\n涨停池: {result['zt_count']} 只, 跌停池: {result['dt_count']} 只")
    elif args.concepts_only:
        result = collect_concepts()
        print(f"\n概念板块: {result['concepts_count']} 个, 映射: {result['mapping_count']} 条")
    elif args.momentum_only:
        conn = _get_conn()
        trade_date = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        momentum = calc_momentum_ranking(conn, trade_date)
        conn.close()
        print(f"\n📊 {trade_date} 日线动量 TOP 10:")
        for i, s in enumerate(momentum[:10], 1):
            print(f"  {i}. {s['symbol']} {s.get('name', '')}  {s['pct_chg']:+.2f}%")
    elif args.kline_only:
        result = download_watchlist_1min_klines()
        print(f"\n1分钟K线: {result['downloaded']} 只成功, {result['total_bars']} 根")
    elif args.report_only:
        conn = _get_conn()
        trade_date = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        momentum = calc_momentum_ranking(conn, trade_date)
        lb_stats = analyze_limitup_stats(conn, _fmt_date(date.today() - timedelta(1)))
        conn.close()
        report = generate_report(
            trade_date=trade_date,
            zt_result={"zt_count": 0, "dt_count": 0, "zt_symbols": [], "dt_symbols": []},
            lb_stats=lb_stats,
            momentum=momentum,
            concept_result={"concepts_count": 0, "mapping_count": 0},
            kline_result={"downloaded": 0, "failed": 0, "symbols": [], "total_bars": 0},
        )
        print("\n" + report)
    else:
        # 全流程
        result = run_pre_market(args.date)
        print("\n" + result.get("report", "报告生成失败"))
