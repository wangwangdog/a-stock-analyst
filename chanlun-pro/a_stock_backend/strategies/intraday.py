"""
盘中策略引擎增强版
在 09:30-15:00 执行：
1. 读取实时行情（腾讯接口）
2. 情绪扫描：实时涨停/跌停/炸板计数（全市场从 stock_daily 取昨收算涨停价）
3. 封单估算 + 封成比
4. 撬板量能检测
5. 连板高度统计
6. 监控池触发信号 + 报告生成

保留原始 API 兼容性：run_intraday() -> dict
"""
import logging
import json
import urllib.request
import sqlite3
import os
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("intraday")

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

# 科创/创业板涨停幅度
_ZT_PCT_MAP = {
    "68": 1.20,  # 科创板
    "30": 1.20,  # 创业板
    "8":  1.20,  # 北交所
}


def _get_conn():
    return sqlite3.connect(DB_PATH)


# ──────────────────────────────────────────────
# 主入口（保持返回 dict 兼容）
# ──────────────────────────────────────────────
def run_intraday() -> dict:
    """执行盘中策略扫描"""
    conn = _get_conn()
    try:
        # 1. 获取关注池
        watch_list = _get_watch_list(conn)

        # 2. 腾讯实时行情
        realtime = _fetch_tencent_realtime(watch_list)

        # 3. 全市场基准数据（昨收）
        market_base = _load_full_market_base(conn)

        # 4. 情绪扫描（全市场 + 关注池）
        sentiment = _scan_sentiment(realtime, market_base)

        # 5. 封单估算
        fengdan = _estimate_fengdan(realtime)

        # 6. 封成比
        fengcheng = _calc_fengcheng_ratio(realtime)

        # 7. 撬板检测
        qiaoban = _detect_qiaoban(realtime)

        # 8. 连板高度
        lianban = _calc_lianban_height(conn, watch_list)

        # 9. 信号触发
        signals = _check_signals(realtime, sentiment, market_base)

        # 10. 盘口异动
        anomalies = _get_recent_anomalies(conn, watch_list)

        return {
            "status": "ok",
            "time": datetime.now().strftime("%H:%M:%S"),
            "watch_count": len(watch_list),
            "sentiment": sentiment,
            "fengdan_top": fengdan[:5],
            "fengcheng_top": fengcheng[:5],
            "qiaoban": qiaoban[:5],
            "lianban": lianban,
            "signals": signals[:20],
            "anomalies": anomalies[:10],
            "report": _format_report(
                sentiment, signals, fengdan, anomalies,
                fengcheng=fengcheng, qiaoban=qiaoban, lianban=lianban,
            ),
        }
    except Exception as e:
        logger.error(f"盘中策略失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 基础数据加载
# ──────────────────────────────────────────────
def _get_zt_pct(symbol: str) -> float:
    """根据代码前缀决定涨停幅度"""
    for prefix, pct in _ZT_PCT_MAP.items():
        if symbol.startswith(prefix):
            return pct
    return 1.10  # 主板


def _load_full_market_base(conn) -> dict:
    """从 stock_daily 获取全部股票昨收，计算涨停/跌停价

    Returns:
        {symbol: {"pre_close": float, "zt_price": float, "dt_price": float, "avg_vol_20": float}}
    """
    today_str = date.today().strftime("%Y-%m-%d")

    # 找最近一个完整交易日（< 今天）
    prev = conn.execute(
        "SELECT DISTINCT date FROM stock_daily WHERE date < ? ORDER BY date DESC LIMIT 1",
        (today_str,),
    ).fetchone()
    if not prev:
        # 回退到最新一天
        prev = conn.execute(
            "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 1"
        ).fetchone()
    prev_date = prev[0] if prev else today_str

    rows = conn.execute(
        "SELECT symbol, close, volume FROM stock_daily WHERE date = ?",
        (prev_date,),
    ).fetchall()

    result = {}
    for symbol, close, volume in rows:
        close = close or 0
        zt_pct = _get_zt_pct(symbol)
        result[symbol] = {
            "pre_close": close,
            "zt_price": round(close * zt_pct, 2),
            "dt_price": round(close * (2 - zt_pct), 2),  # 跌停 = close * (1 - (zt_pct-1))
            "prev_volume": volume or 0,
        }
    logger.info(f"全市场基准加载: {len(result)} 只, 日期 {prev_date}")
    return result


def _get_watch_list(conn) -> list:
    """获取关注池：策略选股结果 + 自选股"""
    symbols = set()
    picks = conn.execute(
        "SELECT DISTINCT symbol FROM strategy_picks ORDER BY date DESC LIMIT 30"
    ).fetchall()
    for (sym,) in picks:
        if sym:
            symbols.add(sym)
    favs = conn.execute(
        "SELECT symbol FROM favorites LIMIT 30"
    ).fetchall()
    for (sym,) in favs:
        if sym:
            symbols.add(sym)
    # 额外补入昨日涨停股（可能有连板机会）
    today_str = date.today().strftime("%Y-%m-%d")
    zt_list = conn.execute(
        "SELECT symbol FROM zt_pool WHERE date = ? AND fd_amount > 0 ORDER BY lb_count DESC LIMIT 20",
        (today_str,),
    ).fetchall()
    for (sym,) in zt_list:
        if sym:
            symbols.add(sym)
    return list(symbols)[:50]  # 腾讯接口限制50只


# ──────────────────────────────────────────────
# 腾讯实时行情
# ──────────────────────────────────────────────
def _fetch_tencent_realtime(codes: list) -> list:
    """调用腾讯实时行情接口"""
    if not codes:
        return []
    prefixed = []
    for c in codes:
        c = c.strip()
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "http://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk")
    except Exception as e:
        logger.warning(f"腾讯行情接口失败: {e}")
        return []

    result = []
    for line in raw.strip().split(";") if ";" in raw else [raw]:
        if not line or "=" not in line:
            continue
        parts = line.split("=")
        if len(parts) < 2:
            continue
        fields = parts[1].strip('"').split("~")
        if len(fields) < 40:
            continue
        try:
            code = fields[2]
            price = float(fields[3]) if fields[3] else 0
            pre_close = float(fields[4]) if fields[4] else 0
            open_p = float(fields[5]) if fields[5] else 0
            volume = int(fields[6]) if fields[6] else 0
            high = float(fields[33]) if fields[33] else 0
            low = float(fields[34]) if fields[34] else 0
            # 腾讯接口: 9-18 买一到买五价/量, 19-28 卖一到卖五价/量
            bid1 = float(fields[9]) if fields[9] else 0
            bid1_vol = int(fields[10]) if fields[10] else 0
            ask1 = float(fields[19]) if fields[19] else 0
            ask1_vol = int(fields[20]) if fields[20] else 0
            name = fields[1]

            # 成交额（万元 → 元）
            turnover_wan = float(fields[37]) if fields[37] else 0
            turnover = turnover_wan * 10000  # 元

            # 换手率
            turnover_rate = float(fields[39]) if fields[39] else 0

            pct = round((price / pre_close - 1) * 100, 2) if pre_close else 0
            zt_pct = _get_zt_pct(code)
            zt_price = round(pre_close * zt_pct, 2)
            dt_price = round(pre_close * (2 - zt_pct), 2)

            result.append({
                "code": code,
                "name": name,
                "price": price,
                "pre_close": pre_close,
                "pct": pct,
                "volume": volume,           # 手
                "turnover": turnover,        # 元
                "turnover_wan": turnover_wan,  # 万元
                "turnover_rate": turnover_rate,
                "high": high,
                "low": low,
                "bid1": bid1,
                "bid1_vol": bid1_vol,        # 手
                "ask1": ask1,
                "ask1_vol": ask1_vol,
                "zt_price": zt_price,
                "dt_price": dt_price,
                "zt_pct": zt_pct,
                "is_limit_up": price >= zt_price,
                "is_limit_down": price <= dt_price,
                "is_zt_board": price >= zt_price and bid1_vol > 0,  # 封涨停
                "is_dt_board": price <= dt_price and ask1_vol > 0,  # 封跌停
            })
        except (ValueError, IndexError):
            continue
    return result


# ──────────────────────────────────────────────
# 情绪扫描（增强：全市场涨停/跌停计数 + 情绪阶段）
# ──────────────────────────────────────────────
def _scan_sentiment(realtime: list, market_base: dict = None) -> dict:
    """情绪扫描：涨停/跌停计数（全市场 + 关注池）

    Args:
        realtime: 关注池实时行情
        market_base: 全市场基准数据（_load_full_market_base 返回）

    Returns:
        dict with zt_count, dt_count, zb_count (炸板), 情绪阶段等信息
    """
    # ── 关注池实时统计 ──
    zt_count = sum(1 for s in realtime if s.get("is_limit_up"))
    dt_count = sum(1 for s in realtime if s.get("is_limit_down"))
    zt_board = sum(1 for s in realtime if s.get("is_zt_board"))   # 封住的
    zb_count = zt_count - zt_board                                 # 炸板 = 触及涨停 - 封住
    up_5 = sum(1 for s in realtime if s.get("pct", 0) > 5)
    down_5 = sum(1 for s in realtime if s.get("pct", 0) < -5)

    # ── 全市场理论统计（从 market_base 推算） ──
    market_zt_count = 0
    market_dt_count = 0
    if market_base:
        for s in realtime:
            code = s.get("code", "")
            base = market_base.get(code)
            if base:
                # 用实时价格 vs 理论涨停/跌停价
                if s["price"] >= base["zt_price"]:
                    market_zt_count += 1
                elif s["price"] <= base["dt_price"]:
                    market_dt_count += 1

    # ── 情绪阶段判断 ──
    phase = _judge_sentiment_phase(zt_count, dt_count, zb_count)

    return {
        "zt_count": zt_count,
        "dt_count": dt_count,
        "zb_count": zb_count,
        "zt_board": zt_board,
        "up_5_count": up_5,
        "down_5_count": down_5,
        "total_watch": len(realtime),
        "market_zt_count": market_zt_count,
        "market_dt_count": market_dt_count,
        "phase": phase,
    }


def _judge_sentiment_phase(zt: int, dt: int, zb: int) -> dict:
    """判断情绪阶段"""
    # 简单规则：关注池情绪阶段
    total = zt + dt + zb
    if total == 0:
        stage = "平淡"
        score = 50
    elif zt >= 5 and zb <= 1:
        stage = "亢奋"
        score = 90
    elif zt >= 3 and zb <= 2:
        stage = "活跃"
        score = 75
    elif zt >= 1 and zb <= zt:
        stage = "温和"
        score = 60
    elif dt >= 3:
        stage = "恐慌"
        score = 20
    elif dt >= 1:
        stage = "低迷"
        score = 35
    else:
        stage = "平淡"
        score = 50

    return {
        "stage": stage,
        "score": score,
        "label": f"{stage}({score})",
    }


# ──────────────────────────────────────────────
# 封单估算（已有）
# ──────────────────────────────────────────────
def _estimate_fengdan(realtime: list) -> list:
    """封单估算：涨停股票用买一量×价格"""
    fengdan_list = []
    for s in realtime:
        if s.get("is_limit_up") and s.get("bid1_vol", 0) > 0:
            fd_amount = s["bid1_vol"] * 100 * s["price"]
            fengdan_list.append({
                "code": s["code"],
                "name": s["name"],
                "fd_amount_yi": round(fd_amount / 1e8, 2),
                "fd_amount": fd_amount,
                "bid1_vol": s["bid1_vol"],
                "price": s["price"],
            })
    return sorted(fengdan_list, key=lambda x: x["fd_amount_yi"], reverse=True)


# ──────────────────────────────────────────────
# 封成比计算（新增）
# ──────────────────────────────────────────────
def _calc_fengcheng_ratio(realtime: list) -> list:
    """封成比 = 封单金额 / 当日成交额

    封成比 > 1 表示封单超过当日成交，封板强；
    封成比 < 0.5 表示封板弱，容易炸板。
    """
    results = []
    for s in realtime:
        if not s.get("is_limit_up") or s.get("bid1_vol", 0) <= 0:
            continue
        fengdan_amount = s["bid1_vol"] * 100 * s["price"]  # 元
        turnover = s.get("turnover", 0)  # 元
        if turnover <= 0:
            continue
        ratio = round(fengdan_amount / turnover, 2)
        results.append({
            "code": s["code"],
            "name": s["name"],
            "fengdan_amount_yi": round(fengdan_amount / 1e8, 2),
            "turnover_yi": round(turnover / 1e8, 2),
            "fengcheng_ratio": ratio,
            "strength": "强封" if ratio >= 3 else ("中封" if ratio >= 1 else "弱封"),
        })
    return sorted(results, key=lambda x: x["fengcheng_ratio"], reverse=True)


# ──────────────────────────────────────────────
# 撬板量能检测（新增）
# ──────────────────────────────────────────────
def _detect_qiaoban(realtime: list) -> list:
    """撬板检测：跌停附近且成交量异常放大

    逻辑：当前价 <= 跌停价*1.02（接近跌停），且
    买一量突增（相对卖一），或者成交明显放大。
    """
    results = []
    for s in realtime:
        price = s.get("price", 0)
        dt_price = s.get("dt_price", 0)
        if dt_price <= 0:
            continue
        # 接近跌停（跌幅 >= 8% 或在跌停价1%内）
        near_dt = price <= dt_price * 1.01 and price > 0
        if not near_dt and s.get("pct", 0) >= -8:
            continue

        # 撬板特征1：买一量 > 卖一量（有资金在接）
        bid_vol = s.get("bid1_vol", 0)
        ask_vol = s.get("ask1_vol", 0)
        vol_ratio = round(bid_vol / max(ask_vol, 1), 2)

        # 撬板特征2：已打开跌停（price > dt_price）
        opened = price > dt_price and s.get("is_limit_down") is False

        if (bid_vol > ask_vol * 2 and bid_vol > 100) or opened:
            results.append({
                "code": s["code"],
                "name": s["name"],
                "price": price,
                "pct": s.get("pct", 0),
                "bid1_vol": bid_vol,
                "ask1_vol": ask_vol,
                "bid_ask_ratio": vol_ratio,
                "status": "已撬开" if opened else "资金承接",
            })
    return sorted(results, key=lambda x: x.get("bid1_vol", 0), reverse=True)


# ──────────────────────────────────────────────
# 连板高度统计（新增）
# ──────────────────────────────────────────────
def _calc_lianban_height(conn, watch_list: list = None) -> dict:
    """连板高度：从 zt_pool 表统计

    Returns:
        dict with:
            - max_height: 最高连板数
            - top_stocks: 连板TOP5
            - distribution: 连板分布 {1: N, 2: N, ...}
    """
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            """SELECT symbol, name, lb_count, fd_amount
               FROM zt_pool
               WHERE date = ? AND fd_amount > 0
               ORDER BY lb_count DESC
               LIMIT 20""",
            (today_str,),
        ).fetchall()

        stocks = []
        dist = {}
        max_height = 0
        for symbol, name, lb, fd in rows:
            fd_yi = round((fd or 0) / 1e8, 2)
            stocks.append({
                "symbol": symbol,
                "name": name or symbol,
                "lb_count": lb or 0,
                "fd_amount_yi": fd_yi,
            })
            if lb:
                max_height = max(max_height, lb)
                dist[lb] = dist.get(lb, 0) + 1

        return {
            "max_height": max_height,
            "top_stocks": stocks[:5],
            "distribution": dict(sorted(dist.items(), reverse=True)),
            "total_limit_up": len(stocks),
        }
    except Exception as e:
        logger.debug(f"连板查询失败: {e}")
        return {"max_height": 0, "top_stocks": [], "distribution": {}, "total_limit_up": 0}


# ──────────────────────────────────────────────
# 信号检测（增强）
# ──────────────────────────────────────────────
def _check_signals(realtime: list, sentiment: dict, market_base: dict = None) -> list:
    """检查交易信号"""
    signals = []
    for s in realtime:
        pct = s.get("pct", 0)
        price = s.get("price", 0)
        volume = s.get("volume", 0)

        # 信号1: 即将涨停 (>9% but not limit)
        if 9 < pct < 9.9:
            signals.append({
                "symbol": s["code"],
                "name": s["name"],
                "signal": "即将涨停",
                "price": price,
                "pct": pct,
            })
        # 信号2: 放量拉升 (>5% 且量>10000手)
        if pct > 5 and volume > 10000:
            signals.append({
                "symbol": s["code"],
                "name": s["name"],
                "signal": "放量拉升",
                "price": price,
                "pct": pct,
                "volume": volume,
            })
        # 信号3: 炸板 (曾涨停但未封住)
        if s.get("is_limit_up") is False and s.get("high", 0) >= s.get("zt_price", 0):
            signals.append({
                "symbol": s["code"],
                "name": s["name"],
                "signal": "炸板回落",
                "price": price,
                "pct": pct,
                "high": s["high"],
                "zt_price": s["zt_price"],
            })
        # 信号4: 封板强化（涨停且有巨量封单 > 1亿）
        if s.get("is_limit_up") and s.get("bid1_vol", 0) * 100 * price > 1e8:
            signals.append({
                "symbol": s["code"],
                "name": s["name"],
                "signal": "巨量封板",
                "price": price,
                "pct": pct,
                "fd_amount_yi": round(s["bid1_vol"] * 100 * price / 1e8, 2),
            })
        # 信号5: 跌停打开（撬板）
        if s.get("is_limit_down") is False and s.get("low", 0) <= s.get("dt_price", 0) and pct > -5:
            signals.append({
                "symbol": s["code"],
                "name": s["name"],
                "signal": "跌停打开",
                "price": price,
                "pct": pct,
                "low": s["low"],
            })
        # 信号6: 封成比异常（高）
        if s.get("is_limit_up") and s.get("bid1_vol", 0) > 0:
            fengdan_amount = s["bid1_vol"] * 100 * price
            turnover = s.get("turnover", 0)
            if turnover > 0:
                fcr = fengdan_amount / turnover
                if fcr >= 5:
                    signals.append({
                        "symbol": s["code"],
                        "name": s["name"],
                        "signal": "超高封成比",
                        "price": price,
                        "pct": pct,
                        "fengcheng_ratio": round(fcr, 2),
                    })
    return signals


# ──────────────────────────────────────────────
# 盘口异动（已有）
# ──────────────────────────────────────────────
def _get_recent_anomalies(conn, watch_list: list) -> list:
    """从 market_anomaly 表获取最近的盘口异动"""
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            """SELECT symbol, anomaly_type, occur_time, price, volume
               FROM market_anomaly
               WHERE created_at >= ?
               ORDER BY occur_time DESC
               LIMIT 50""",
            (today_str,),
        ).fetchall()

        result = []
        for r in rows:
            symbol, atype, occur_time, price, volume = r
            name = ""
            for ws in watch_list:
                if symbol == ws or symbol.endswith(ws) or ws.endswith(symbol):
                    try:
                        name_row = conn.execute(
                            "SELECT name FROM all_stock_info WHERE code=? LIMIT 1",
                            (symbol,),
                        ).fetchone()
                        if name_row:
                            name = name_row[0]
                    except Exception:
                        pass
                    break
            result.append({
                "symbol": symbol,
                "name": name or symbol,
                "anomaly_type": atype,
                "occur_time": occur_time,
                "price": price,
            })
        return result
    except Exception as e:
        logger.debug(f"查询盘口异动失败: {e}")
        return []


# ──────────────────────────────────────────────
# 报告生成（增强）
# ──────────────────────────────────────────────
def _format_report(
    sentiment: dict,
    signals: list,
    fengdan_top: list,
    anomalies: list = None,
    **kwargs,
) -> str:
    """生成可读的盘中扫描报告

    额外关键字参数：
        fengcheng: list - 封成比列表
        qiaoban: list - 撬板检测列表
        lianban: dict - 连板高度
    """
    now = datetime.now()
    lines = [f"⏰ {now.strftime('%H:%M')} 盘中扫描"]

    # ── 情绪总览 ──
    phase = sentiment.get("phase", {})
    phase_label = phase.get("label", "N/A") if phase else "N/A"
    lines.append(
        f"📊 情绪: {phase_label}  "
        f"涨停{sentiment['zt_count']} 跌停{sentiment['dt_count']}  "
        f"涨>5%{sentiment['up_5_count']} 跌>5%{sentiment['down_5_count']}"
    )

    # 全市场数据
    mzt = sentiment.get("market_zt_count", 0)
    mdt = sentiment.get("market_dt_count", 0)
    if mzt or mdt:
        lines.append(f"   全市场参考: 涨停{mzt} 跌停{mdt}")

    # 炸板
    zb = sentiment.get("zb_count", 0)
    if zb:
        lines.append(f"💥 炸板 {zb} 只")

    # ── 连板高度 ──
    lianban = kwargs.get("lianban")
    if lianban and lianban.get("total_limit_up", 0) > 0:
        max_h = lianban.get("max_height", 0)
        total_zt = lianban.get("total_limit_up", 0)
        dist = lianban.get("distribution", {})
        dist_str = " ".join(f"{k}板:{v}" for k, v in dist.items())
        lines.append(
            f"📈 连板: 最高{max_h}板 总数{total_zt}只  {dist_str}"
        )
        top_lb = lianban.get("top_stocks", [])
        if top_lb:
            parts = []
            for st in top_lb[:3]:
                parts.append(f"{st['name']}({st['lb_count']}板)")
            lines.append("   " + " ".join(parts))

    # ── 封单TOP ──
    if fengdan_top:
        lines.append(f"\n🔒 封单TOP3:")
        for s in fengdan_top[:3]:
            lines.append(f"  {s['name']}  {s['fd_amount_yi']}亿")

    # ── 封成比 ──
    fengcheng = kwargs.get("fengcheng")
    if fengcheng:
        lines.append(f"\n📐 封成比TOP3:")
        for s in fengcheng[:3]:
            lines.append(
                f"  {s['name']}  {s['fengcheng_ratio']}x "
                f"({s['strength']})  封单{s['fengdan_amount_yi']}亿"
            )

    # ── 撬板检测 ──
    qiaoban = kwargs.get("qiaoban")
    if qiaoban:
        lines.append(f"\n🔨 撬板/承接 ({len(qiaoban)}只):")
        for s in qiaoban[:3]:
            lines.append(
                f"  {s['name']}  {s['status']}  "
                f"{s['pct']:+.2f}%  买一{s['bid1_vol']}手"
            )

    # ── 信号 ──
    if signals:
        lines.append(f"\n⚡ 信号 ({len(signals)}个):")
        for s in signals[:5]:
            lines.append(f"  {s['name']}  {s['signal']}  {s['pct']:+.2f}%")
    else:
        lines.append("\n✅ 无活跃交易信号")

    # ── 盘口异动 ──
    if anomalies:
        lines.append(f"\n📡 盘口异动 ({len(anomalies)}条):")
        for a in anomalies[:5]:
            lines.append(f"  {a['name']}  {a['anomaly_type']}  {a['occur_time']}")

    return "\n".join(lines)
