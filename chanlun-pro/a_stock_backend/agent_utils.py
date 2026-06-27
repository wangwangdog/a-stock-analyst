"""
AI Agent 工具函数集

为 AI 分析师提供量化信号查询接口，让 LLM Agent 在做判断时
能看到 Sequoia-X 策略选股结果等结构化数据。
"""

import json
import logging
from datetime import date

from data.sequoia_engine import get_strategy_signals

logger = logging.getLogger('agent_utils')


def get_strategy_signals_for_agent(ticker: str) -> str:
    """
    AI Agent 工具：获取个股策略信号摘要。

    查询今日/近期该股被哪些 Sequoia-X 策略选中，
    返回人类可读字符串供 LLM 直接使用。

    Args:
        ticker: 股票代码，如 "000001", "600519"

    Returns:
        字符串，如 "海龟突破 ✓ | RPS突破 ✓" 或 "无策略信号"
    """
    try:
        signals = get_strategy_signals(ticker)
        if not signals:
            return "无策略信号触发"
        return f"策略信号: {signals}"
    except Exception as e:
        logger.debug(f"获取策略信号失败: {e}")
        return "策略信号: 查询异常"


def get_strategy_summary_for_agent() -> str:
    """
    AI Agent 工具：获取今日策略选股全局摘要。

    Returns:
        字符串，描述今日哪些策略选出了哪些股票
    """
    try:
        from data.sequoia_engine import get_todays_picks
        picks = get_todays_picks()
        if not picks:
            return "今日暂无策略选股结果"

        by_strategy = {}
        for p in picks:
            by_strategy.setdefault(p["strategy"], []).append(p["symbol"])

        lines = ["## 今日策略选股摘要"]
        name_map = dict((k, n) for k, n, _ in [
            ("ma_volume","均线放量"),("turtle_trade","海龟交易"),
            ("high_tight_flag","高窄旗形"),("limit_up_shakeout","涨停洗盘"),
            ("uptrend_limit_down","跌停反包"),("rps_breakout","RPS突破"),
        ])
        for strategy, symbols in by_strategy.items():
            sname = name_map.get(strategy, strategy)
            display = ", ".join(symbols[:5])
            if len(symbols) > 5:
                display += f" ... 共 {len(symbols)} 只"
            lines.append(f"- **{sname}**: {display}")

        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"获取策略摘要失败: {e}")
        return "策略摘要: 查询异常"


def format_prompt_enhancement(ticker: str, stock_name: str = "") -> str:
    """
    生成 AI 分析提示词的增强段落。

    在调用 AI 分析时，将这段文字追加到 prompt 末尾，
    让 AI 能看到量化策略信号。

    Args:
        ticker: 股票代码
        stock_name: 股票名称（可选）

    Returns:
        提示词增强段落
    """
    signals = get_strategy_signals_for_agent(ticker)
    return (
        f"\n\n【量化策略信号】\n"
        f"股票 {ticker} {stock_name} 当前被 Sequoia-X 量化选股系统标记如下：\n"
        f"{signals}\n\n"
        f"注意：策略信号仅作为参考，不代表投资建议。请结合技术面和基本面综合判断。"
    )


# 工具注册表：供 TradingAgentsGraph 调用
TOOL_REGISTRY = {
    "get_strategy_signals": {
        "name": "get_strategy_signals",
        "description": "获取某只股票被哪些量化选股策略选中",
        "handler": get_strategy_signals_for_agent,
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "股票代码，如 000001"
                }
            },
            "required": ["ticker"]
        }
    },
    "get_strategy_summary": {
        "name": "get_strategy_summary",
        "description": "获取今日量化选股策略的全局结果摘要",
        "handler": get_strategy_summary_for_agent,
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}
