"""
快速分析 - 轻量级 AI 研判
只关注两个核心问题：主力资金是否介入 + 形态是否见底
单次 LLM 调用，毫秒级响应
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import sqlite3
from langchain_openai import ChatOpenAI

logger = logging.getLogger('quick_analysis')

# SQLite cache path — merged DB (chanlun_klines)
_HOME_DB = Path(os.getenv("HOME", "/home/dogzi")) / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"
DB_PATH = str(_HOME_DB)


def _normalize_symbol(ticker: str) -> str:
    """000001.SH → 000001, 000001.SZ → 000001, 688001.SH → 688001"""
    return ticker.split(".")[0].strip()


def _get_kline_from_cache(ticker: str, days: int = 60) -> list[dict]:
    """
    从 SQLite 数据库读取该股票最近 days 天的日线数据
    优先查 kline_cache（daily），回退到 stock_daily。
    返回按 trade_date 降序排列的列表
    """
    symbol = _normalize_symbol(ticker)
    if not Path(DB_PATH).exists():
        logger.warning(f"[快速分析] 缓存数据库不存在: {DB_PATH}")
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # 1. kline_cache daily
        rows = conn.execute(f"""
            SELECT trade_date, open, close, high, low, volume, amount, source
            FROM kline_cache
            WHERE symbol = ? AND period = 'daily'
            ORDER BY trade_date DESC
            LIMIT {days}
        """, (symbol,)).fetchall()
        if rows:
            conn.close()
            return [dict(r) for r in rows]
        # 2. 回退：stock_daily（原 sequoia 日线表）
        rows = conn.execute(f"""
            SELECT date as trade_date, open, close, high, low, volume,
                   COALESCE(turnover, 0) as amount, 'daily' as source
            FROM stock_daily
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT {days}
        """, (symbol,)).fetchall()
        conn.close()
        if rows:
            return [dict(r) for r in rows]
        return []
    except Exception as e:
        logger.warning(f"[快速分析] 缓存读取失败: {e}")
        return []


def _build_kline_summary(ticker: str) -> dict:
    symbol = _normalize_symbol(ticker)
    """取近期 K 线和技术指标，返回结构化摘要"""
    result = {"klines": "", "bigbuy": "", "error": None}

    # 1. 从 SQLite kline_cache 读取（baostock/akshare 均可）
    klines = _get_kline_from_cache(ticker, days=60)
    if klines:
        lines = []
        for r in klines[:30]:
            date_str = r["trade_date"][:10]
            vol = r.get("volume", 0) or 0
            amount = r.get("amount", 0) or 0
            lines.append(
                f"{date_str} 开:{r['open']} 收:{r['close']} "
                f"高:{r['high']} 低:{r['low']} 量:{vol:.0f} 额:{amount:.0f}"
            )
        result["klines"] = "\n".join(lines)
        if klines:
            result["latest_close"] = klines[0].get("close", "")
            result["latest_date"] = klines[0].get("trade_date", "")[:10]
        return result

    # 2. 回退：AKShare 直连
    result["error"] = "缓存无数据"
    try:
        import akshare as ak
        end_str = datetime.now().strftime("%Y%m%d")
        start_str = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
        adf = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                  start_date=start_str, end_date=end_str, adjust="qfq")
        if adf is not None and not adf.empty:
            adf = adf.sort_values('日期', ascending=False).head(30)
            lines = []
            for _, r in adf.iterrows():
                lines.append(
                    f"{r['日期']} 开:{r['开盘']} 收:{r['收盘']} "
                    f"高:{r['最高']} 低:{r['最低']} 量:{r['成交量']} 涨幅:{r['涨跌幅']}%"
                )
            result["klines"] = "\n".join(lines)
            result["latest_close"] = adf.iloc[0]["收盘"]
            result["latest_date"] = str(adf.iloc[0]["日期"])
    except Exception as e:
        result["error"] = f"缓存+直连均失败: {e}"

    return result


def quick_analyze(
    ticker: str,
    stock_name: str = "",
    llm_provider: str = "deepseek",
    api_key: str = None,
    base_url: str = None
) -> dict:
    """
    快速分析 - 一个 LLM 调用回答两个核心问题。
    
    Returns:
        {"verdict": str, "reasoning": str, "signal": str}  
        signal: "buy" / "watch" / "pass"  
    """
    if api_key is None:
        if llm_provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
        elif llm_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
    
    if base_url is None and llm_provider == "deepseek":
        base_url = "https://api.deepseek.com"
    
    # 获取数据
    data = _build_kline_summary(ticker)
    kline_str = data["klines"]
    if not kline_str:
        return {
            "success": False,
            "error": f"无法获取 {ticker} 的行情数据 (缓存无数据、AKShare 不可用)"
        }
    
    last_close = data.get("latest_close", "")
    latest_date = data.get("latest_date", "")
    date_note = f" (数据截止 {latest_date})" if latest_date else ""

    prompt = f"""你是一位A股短线技术分析师。请基于以下数据，对股票 {ticker} {stock_name} 做快速研判。

截止数据时间{date_note}，最新收盘价: {last_close}

近期K线数据(最近30个交易日，最新在前):
{kline_str}

请分析以下两个核心问题，用JSON格式回答:

1. **主力是否近期介入**: 通过量价关系判断 - 近期是否有放量上涨、大单买入增多等主力介入迹象？
2. **形态是否见底**: 通过K线形态判断 - 当前是否处于阶段性底部区域？是否有止跌信号（锤子线、启明星、底背离等）？

回答JSON格式:
{{
  "main_force_judgment": "有主力介入迹象/无明显主力迹象/主力出货",
  "bottom_pattern": "已见底/底部区域/仍在下跌中/需观察",
  "signal": "buy/watch/pass",
  "reasoning": "用30字以内的短话概括判断依据"
}}

只输出JSON，不要其他内容。"""
    
    try:
        llm = ChatOpenAI(
            model="deepseek-chat",
            openai_api_key=api_key,
            openai_api_base=base_url,
            temperature=0.3,
            max_tokens=500,
        )
        resp = llm.invoke(prompt)
        text = resp.content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(text)
        result["success"] = True
        result["last_price"] = last_close
        result["latest_date"] = latest_date
        return result
    except Exception as e:
        logger.error(f"快速分析失败: {e}")
        return {
            "success": False,
            "error": f"分析失败: {str(e)}"
        }
