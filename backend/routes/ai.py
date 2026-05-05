"""
AI 分析 API 路由
- 快速分析: 瞬时研判，关注主力介入 + 底部形态
- 深度分析: 完整多 Agent 流水线(含流式进度)
"""

import os
import logging
import json
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger('ai_route')
router = APIRouter(prefix="/api/ai", tags=["AI 分析"])

# Progress store
_analysis_progress: dict = {}

def _set_progress(task_id: str, agent: str, status: str, detail: str = ""):
    _analysis_progress[task_id] = {
        "agent": agent,
        "status": status,
        "detail": detail,
        "time": datetime.now().strftime("%H:%M:%S"),
    }

def get_progress(task_id: str) -> dict:
    return _analysis_progress.get(task_id, {})

def clear_progress(task_id: str):
    _analysis_progress.pop(task_id, None)


class DeepAnalyzeRequest(BaseModel):
    stock_code: str
    trade_date: str = None
    llm_provider: str = "deepseek"
    deep_think_model: str = "deepseek-chat"
    quick_think_model: str = "deepseek-chat"
    max_debate_rounds: int = 1
    enable_checkpoint: bool = False


class QuickAnalyzeRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    llm_provider: str = "deepseek"


@router.get("/providers")
async def list_providers():
    return {
        "providers": [
            {"id": "deepseek", "name": "DeepSeek", "models": ["deepseek-chat", "deepseek-reasoner"]},
            {"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "o4-mini"]},
            {"id": "qwen", "name": "通义千问", "models": ["qwen-plus", "qwen-max", "qwen-turbo"]},
            {"id": "glm", "name": "智谱 GLM", "models": ["glm-4-plus", "glm-4-air"]},
        ]
    }


@router.post("/quick")
async def quick_analyze(request: QuickAnalyzeRequest):
    """快速分析 - 单次 LLM 调用，秒级响应"""
    from quick_analysis import quick_analyze as _quick

    if not request.stock_code.strip():
        raise HTTPException(status_code=400, detail="请提供股票代码")

    key = os.getenv(f"{request.llm_provider.upper()}_API_KEY")
    if not key:
        return {"success": False, "error": f"未配置 {request.llm_provider.upper()}_API_KEY"}

    try:
        logger.info(f"⚡ 快速分析: {request.stock_code}")
        result = _quick(
            ticker=request.stock_code,
            stock_name=request.stock_name,
            llm_provider=request.llm_provider,
            api_key=key,
        )
        return result
    except Exception as e:
        logger.error(f"快速分析失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/analyze")
async def deep_analyze(request: DeepAnalyzeRequest):
    """深度分析 - 完整多 Agent 流水线"""
    from ai_analysis import run_ai_analysis, format_decision_json

    code = request.stock_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请提供股票代码")

    provider = request.llm_provider
    env_key_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "glm": "ZHIPU_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    required_key = env_key_map.get(provider)
    if required_key and not os.getenv(required_key):
        return {"success": False, "error": f"未配置 {required_key} 环境变量"}

    try:
        logger.info(f"🎯 深度分析: {code} provider={provider}")

        final_state, decision = run_ai_analysis(
            stock_code=code,
            trade_date=request.trade_date or datetime.now().strftime("%Y-%m-%d"),
            llm_provider=provider,
            deep_think_model=request.deep_think_model,
            quick_think_model=request.quick_think_model,
            max_debate_rounds=request.max_debate_rounds,
            enable_checkpoint=request.enable_checkpoint,
        )

        result = format_decision_json(decision)
        if final_state:
            result['analyst_details'] = {
                'market_analysis': (final_state.get('market_analysis') or '')[:500],
            }
        return {"success": True, "data": result}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"深度分析失败: {e}", exc_info=True)
        return {"success": False, "error": f"分析过程出错: {str(e)}"}


@router.post("/analyze/stream")
async def deep_analyze_stream(request: DeepAnalyzeRequest):
    """深度分析(流式进度) - 实时推送每个 Agent 的完成状态"""
    from ai_analysis import run_ai_analysis, format_decision_json, _make_progress_cb, get_progress

    code = request.stock_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请提供股票代码")

    provider = request.llm_provider
    required_key = f"{provider.upper()}_API_KEY"
    if not os.getenv(required_key):
        raise HTTPException(status_code=400, detail=f"未配置 {required_key}")

    task_id = str(uuid.uuid4())[:8]

    async def event_stream():
        progress_cb = _make_progress_cb(task_id)
        progress_cb(json.dumps({"agent": "🚀 启动", "content": "初始化分析引擎，加载多Agent系统..."}, ensure_ascii=False))

        yield f"data: {json.dumps({'task_id': task_id, 'agent': '🚀 启动', 'status': '分析初始化...'})}\n\n"

        import threading, time
        result_container = {}

        def run_analysis():
            try:
                final_state, decision = run_ai_analysis(
                    stock_code=code,
                    trade_date=request.trade_date or datetime.now().strftime("%Y-%m-%d"),
                    llm_provider=provider,
                    deep_think_model=request.deep_think_model,
                    quick_think_model=request.quick_think_model,
                    max_debate_rounds=request.max_debate_rounds,
                    enable_checkpoint=request.enable_checkpoint,
                    progress_callback=progress_cb,
                    task_id=task_id,
                )
                result_container['final_state'] = final_state
                result_container['decision'] = decision
                result_container['success'] = True
            except Exception as e:
                result_container['success'] = False
                result_container['error'] = str(e)
                logger.error(f"流式分析失败: {e}", exc_info=True)

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

        last_agent = ""
        while thread.is_alive():
            p = get_progress(task_id)
            agent = p.get('agent', '')
            if agent and agent != last_agent:
                last_agent = agent
                yield f"data: {json.dumps(p)}\n\n"
            await asyncio.sleep(1)

        thread.join()

        # Final result with complete analysis content
        if result_container.get('success'):
            decision = result_container['decision']
            result = format_decision_json(decision)
            fs = result_container.get('final_state', {})
            
            # 提取完整分析报告
            def _safe_str(v, default=""):
                if isinstance(v, str):
                    return v
                return str(v) if v else default
            
            # 基本面分析师完整内容
            fundamentals_report = _safe_str(fs.get('fundamentals_report', ''))
            
            # 多头研究员完整内容
            bull_content = ""
            debate_state = fs.get('investment_debate_state', {})
            if isinstance(debate_state, dict):
                bull_content = _safe_str(debate_state.get('bull_history', ''))
                if not bull_content:
                    bull_content = _safe_str(debate_state.get('current_response', ''))
            
            # 空头研究员完整内容
            bear_content = ""
            if isinstance(debate_state, dict):
                bear_content = _safe_str(debate_state.get('bear_history', ''))
                if not bear_content and bull_content:
                    # fallback: same current_response
                    pass
            
            # 市场/新闻/情绪报告完整内容
            market_report = _safe_str(fs.get('market_report', ''))
            news_report = _safe_str(fs.get('news_report', ''))
            sentiment_report = _safe_str(fs.get('sentiment_report', fs.get('social_media_report', '')))
            trader_plan = _safe_str(fs.get('trader_investment_plan', ''))
            risk_assessment = _safe_str(fs.get('risk_assessment', ''))
            
            final_decision = {
                'signal_type': result.get('signal', {}).get('type', 'hold'),
                'confidence': result.get('signal', {}).get('confidence', 0),
                'reasoning': result.get('reasoning', ''),
                'risk_level': result.get('risk_level', 'medium'),
            }

            result['full_analysis'] = {
                'fundamentals_report': fundamentals_report,
                'bull_analysis': bull_content,
                'bear_analysis': bear_content,
                'market_report': market_report,
                'news_report': news_report,
                'sentiment_report': sentiment_report,
                'trader_plan': trader_plan,
                'risk_assessment': risk_assessment,
                'final_decision': final_decision,
            }
            
            clear_progress(task_id)
            yield f"data: {json.dumps({'done': True, 'result': result, 'task_id': task_id}, ensure_ascii=False)}\n\n"
        else:
            yield f"data: {json.dumps({'done': True, 'error': result_container.get('error', '未知错误'), 'task_id': task_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/progress/{task_id}")
async def get_analysis_progress(task_id: str):
    """获取指定分析任务的进度"""
    return get_progress(task_id)
