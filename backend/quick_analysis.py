"""
快速分析 - 轻量级 AI 研判
只关注两个核心问题：主力资金是否介入 + 形态是否见底
单次 LLM 调用，毫秒级响应
"""

import os
import json
import logging
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI

logger = logging.getLogger('quick_analysis')


def _build_kline_summary(ticker: str) -> dict:
    """取近期 K 线和技术指标，返回结构化摘要"""
    result = {"klines": "", "bigbuy": "", "error": None}
    
    # 1. Try project's cached data first
    try:
        import data.akshare_fetcher as akf
        df = akf.get_daily_kline(ticker)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date', ascending=False).head(30)
            lines = []
            for _, r in df.iterrows():
                pct = r.get('pct_change', r.get('涨跌幅', ''))
                vol = r.get('volume', r.get('成交量', ''))
                lines.append(
                    f"{r['trade_date']} 开:{r['open']} 收:{r['close']} "
                    f"高:{r['high']} 低:{r['low']} 量:{vol} 涨幅:{pct}%"
                )
            result["klines"] = "\n".join(lines)
            return result
    except Exception as e:
        result["error"] = f"缓存获取失败: {e}"
    
    # 2. Fallback: AKShare directly
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        # AKShare uses YYYYMMDD format (no dashes)
        end_str = datetime.now().strftime("%Y%m%d")
        start_str = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
        adf = ak.stock_zh_a_hist(symbol=ticker, period="daily",
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
    except Exception as e:
        result["error"] = f"直接获取失败: {e}"
    
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
            "error": f"无法获取 {ticker} 的行情数据"
        }
    
    # 取最后一根 K 线的最新价格
    last_close = ""
    if kline_str:
        last_line = kline_str.split("\n")[0]
        parts = last_line.split()
        for p in parts:
            if p.startswith("收:"):
                last_close = p.replace("收:", "")
                break

    # 获取策略信号
    try:
        from agent_utils import get_strategy_signals_for_agent
        strategy_signals = get_strategy_signals_for_agent(ticker)
    except Exception:
        strategy_signals = ""

    strategy_block = f"\n量化策略信号: {strategy_signals}\n" if strategy_signals else ""

    prompt = f"""你是一位A股短线技术分析师。请基于以下数据，对股票 {ticker} {stock_name} 做快速研判。

截止数据时间，最新收盘价: {last_close}

近期K线数据(最近30个交易日，最新在前):
{kline_str}

资金流向: {data.get('bigbuy', '暂无')}
{strategy_block}
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
        # 提取 JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(text)
        result["success"] = True
        result["last_price"] = last_close
        return result
    except Exception as e:
        logger.error(f"快速分析失败: {e}")
        return {
            "success": False,
            "error": f"分析失败: {str(e)}"
        }
