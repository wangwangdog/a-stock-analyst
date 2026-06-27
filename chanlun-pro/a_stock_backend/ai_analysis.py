"""
AI 分析集成模块
将 TradingAgents-CN 的多 Agent 研判集成到 a-stock-analyst
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger('ai_analysis')

# 设置环境变量
os.environ['USE_MONGODB_STORAGE'] = 'false'
os.environ['DISABLE_CHROMADB'] = 'true'
os.environ['ONLINE_TOOLS_ENABLED'] = 'true'
os.environ['ONLINE_NEWS_ENABLED'] = 'true'
os.environ['REALTIME_DATA_ENABLED'] = 'true'

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG


# Global progress store for streaming
_analysis_progress: dict = {}

def get_progress(task_id: str) -> dict:
    return _analysis_progress.get(task_id, {})

def clear_progress(task_id: str):
    _analysis_progress.pop(task_id, None)

def _make_progress_cb(task_id: str):
    """Create a callback for TradingAgentsGraph progress updates.
    Receives a JSON string: {"agent": "...", "content": "..."}
    """
    import json
    def cb(payload_str: str):
        try:
            payload = json.loads(payload_str) if isinstance(payload_str, str) else {}
        except json.JSONDecodeError:
            payload = {"agent": payload_str, "content": ""}
        _analysis_progress[task_id] = {
            "agent": payload.get("agent", ""),
            "status": "完成",
            "content": (payload.get("content", "") or "")[:500],
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    return cb


def run_ai_analysis(
    stock_code: str,
    trade_date: str = None,
    llm_provider: str = "deepseek",
    deep_think_model: str = "deepseek-chat",
    quick_think_model: str = "deepseek-chat",
    openai_base_url: str = None,
    openai_api_key: str = None,
    max_debate_rounds: int = 1,
    enable_checkpoint: bool = False,
    progress_callback=None,
    task_id: str = None,
) -> Tuple[Dict, Dict]:
    """
    对 A 股执行多 Agent AI 分析。
    
    Args:
        stock_code: A 股代码 (如 "000001", "600036")
        trade_date: 分析日期 (YYYY-MM-DD)，默认今天
        llm_provider: LLM 供应商 (deepseek, openai, qwen, glm, google 等)
        deep_think_model: 深度推理模型名
        quick_think_model: 快速响应模型名  
        openai_base_url: OpenAI 兼容 API 地址 (DeepSeek/Qwen 用)
        openai_api_key: API Key
        max_debate_rounds: 最大辩论轮数
        enable_checkpoint: 是否启用检查点恢复
        progress_callback: 进度回调函数
        
    Returns:
        (final_state, decision) 元组
        - final_state: 完整分析状态
        - decision: 结构化交易决策
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    
    # 默认 DeepSeek API 地址
    if openai_base_url is None and llm_provider == "deepseek":
        openai_base_url = "https://api.deepseek.com"
    
    # 从环境变量读取 API Key
    if openai_api_key is None:
        if llm_provider == "deepseek":
            openai_api_key = os.getenv('DEEPSEEK_API_KEY')
        elif llm_provider == "openai":
            openai_api_key = os.getenv('OPENAI_API_KEY')
        elif llm_provider == "qwen":
            openai_api_key = os.getenv('DASHSCOPE_API_KEY')
            openai_base_url = openai_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        elif llm_provider == "glm":
            openai_api_key = os.getenv('ZHIPU_API_KEY')
            openai_base_url = openai_base_url or "https://open.bigmodel.cn/api/paas/v4"
    
    if not openai_api_key:
        raise ValueError(f"需要设置 {llm_provider.upper()}_API_KEY 环境变量或传入 api_key 参数")
    
    # 构建配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = llm_provider
    config["deep_think_llm"] = deep_think_model
    config["quick_think_llm"] = quick_think_model
    config["backend_url"] = openai_base_url
    config["max_debate_rounds"] = max_debate_rounds
    config["max_risk_discuss_rounds"] = max_debate_rounds
    config["checkpoint_enabled"] = enable_checkpoint
    config["output_language"] = "Chinese"  # 中文输出
    
    # 创建图实例
    logger.info(f"🤖 初始化 AI 分析: {stock_code} @ {trade_date}")
    logger.info(f"   LLM: {llm_provider}/{deep_think_model}")
    
    ta = TradingAgentsGraph(debug=True, config=config)
    
    # 执行分析
    logger.info(f"🚀 开始多 Agent 分析：{stock_code}")
    start_time = time.time()
    
    final_state, decision = ta.propagate(
        stock_code, 
        trade_date,
        progress_callback=progress_callback
    )
    
    elapsed = time.time() - start_time
    logger.info(f"✅ 分析完成，耗时 {elapsed:.1f} 秒")
    
    return final_state, decision


def format_decision_report(decision: Dict) -> str:
    """将决策结果格式化为人类可读的报告"""
    lines = []
    lines.append("=" * 50)
    lines.append("📊 AI 多Agent 研判报告")
    lines.append("=" * 50)
    
    if not decision:
        return "分析未产生有效结果"
    
    # 交易决策
    signal = decision.get('trading_signal', 'N/A')
    confidence = decision.get('confidence', 'N/A')
    reason = decision.get('reason', decision.get('reasoning', ''))
    
    lines.append(f"\n📈 交易信号: {signal}")
    lines.append(f"🎯 置信度: {confidence}")
    lines.append(f"💡 理由: {reason}")
    
    # 附加信息
    for key in ['entry_price', 'stop_loss', 'take_profit', 'position_size']:
        if key in decision:
            lines.append(f"   {key}: {decision[key]}")
    
    # 模型信息
    if 'model_info' in decision:
        lines.append(f"\n🤖 模型: {decision['model_info']}")
    
    lines.append("=" * 50)
    return "\n".join(lines)


def format_decision_json(decision: Dict) -> Dict:
    """结构化的决策结果"""
    return {
        "stock_code": decision.get('company_of_interest', ''),
        "trade_date": decision.get('trade_date', ''),
        "signal": {
            "type": decision.get('trading_signal', 'hold'),
            "confidence": decision.get('confidence', 'medium'),
            "direction": decision.get('direction', 'neutral'),
        },
        "reasoning": decision.get('reason', decision.get('reasoning', '')),
        "price_targets": {
            "entry": decision.get('entry_price'),
            "stop_loss": decision.get('stop_loss'),
            "take_profit": decision.get('take_profit'),
        },
        "position": decision.get('position_size'),
        "risk_level": decision.get('risk_level', 'medium'),
        "model_info": decision.get('model_info', ''),
        "performance": decision.get('performance_metrics', {}),
    }


if __name__ == "__main__":
    # 测试运行
    logging.basicConfig(level=logging.INFO)
    print("AI 分析模块加载成功")
    print(f"DEFAULT_CONFIG keys: {list(DEFAULT_CONFIG.keys())}")
