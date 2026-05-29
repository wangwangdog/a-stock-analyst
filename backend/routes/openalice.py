"""
OpenAlice AI 集成路由
- 多资产深度分析
- 持仓健康检查
- 市场摘要
"""

import os
import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger('openalice_route')
router = APIRouter(prefix="/api/openalice", tags=["OpenAlice AI"])

# OpenAlice 配置（本地 Docker 部署）
OPENALICE_MCP_URL = os.getenv("OPENALICE_MCP_URL", "http://127.0.0.1:47332")
OPENALICE_UTA_URL = os.getenv("OPENALICE_UTA_URL", "http://127.0.0.1:47333")
OPENALICE_WEB_URL = os.getenv("OPENALICE_WEB_URL", "http://127.0.0.1:47331")
OPENALICE_TIMEOUT = 60  # 秒

class OpenAliceAnalyzeRequest(BaseModel):
    stock_code: str
    stock_name: Optional[str] = ""
    analysis_type: str = "full"  # 'fundamental', 'technical', 'full'
    language: str = "zh"  # 中文输出

class OpenAliceHealthcheckRequest(BaseModel):
    holdings: list  # [{"code": "600519", "qty": 100, "cost": 12.5}]


@router.get("/status")
async def check_openalice_status():
    """检查 OpenAlice 服务状态"""
    try:
        # 尝试连接 MCP 端口（轻量检查）
        resp = requests.get(f"{OPENALICE_MCP_URL}/health", timeout=3)
        return {
            "success": True,
            "status": "running",
            "mcp_url": OPENALICE_MCP_URL,
            "web_url": OPENALICE_WEB_URL,
        }
    except Exception as e:
        logger.warning(f"OpenAlice 连接检查失败：{e}")
        return {
            "success": False,
            "status": "offline",
            "error": str(e),
            "message": "OpenAlice 服务未启动，请运行：docker compose up -d"
        }


@router.post("/analyze")
async def analyze_stock(request: OpenAliceAnalyzeRequest):
    """
    调用 OpenAlice 进行深度分析
    
    分析内容：
    1. 基本面分析（财务、业务、行业地位）
    2. 技术面判断（趋势、关键位、缠论结构）
    3. 资金面分析（北向、机构、游资）
    4. 风险因素识别
    5. 操作建议（买入/观望/卖出 + 理由）
    """
    code = request.stock_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请提供股票代码")
    
    # 检查 OpenAlice 是否可用
    try:
        requests.get(f"{OPENALICE_MCP_URL}/health", timeout=2)
    except:
        logger.warning("OpenAlice 服务未响应，降级到 LangGraph")
        # TODO: 降级到现有 LangGraph 分析
        return {
            "success": False,
            "error": "OpenAlice 服务未启动",
            "message": "请运行：docker compose up -d OpenAlice",
            "fallback": "建议查看现有 LangGraph 分析或缠论结构"
        }
    
    try:
        # 构建 OpenAlice 研究指令
        prompt = f"""你是 A 股专业投资分析师。请深度分析股票：{code} ({request.stock_name or ''})

分析要求：
1. **基本面**：财务状况、业务模式、行业地位、竞争优势
2. **技术面**：趋势判断、关键支撑/阻力位、缠论结构（中枢、笔、线段）
3. **资金面**：北向资金、机构持仓、游资动向、量价关系
4. **风险因素**：政策风险、业绩风险、流动性风险
5. **操作建议**：买入/观望/卖出，并给出具体理由和价格区间

输出格式（严格 JSON）：
{{
  "analysis": {{
    "fundamental": "...",
    "technical": "...",
    "capital_flow": "...",
    "risk_factors": ["..."],
    "summary": "..."
  }},
  "recommendation": "BUY|HOLD|SELL",
  "confidence": 0-100,
  "price_target": {{
    "support": 0.0,
    "resistance": 0.0
  }},
  "reasoning": "..."
}}

语言：中文
"""
        
        # 调用 OpenAlice MCP 接口（模拟 Claude API 格式）
        # 注意：OpenAlice 实际 API 可能需要调整
        response = requests.post(
            f"{OPENALICE_MCP_URL}/v1/chat/completions",
            json={
                "model": "claude-3-5-sonnet",  # OpenAlice 使用 Claude
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": 2000
            },
            timeout=OPENALICE_TIMEOUT
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenAlice API 错误：{response.status_code}")
        
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 解析 JSON 结果（可能包含 Markdown 代码块）
        import re
        json_match = re.search(r'```json\s*(.+?)\s*```', content, re.DOTALL)
        if json_match:
            ai_result = json.loads(json_match.group(1))
        else:
            # 尝试直接解析
            ai_result = json.loads(content)
        
        # 存入缓存（TODO: 实现 Redis 缓存）
        # cache_key = f"openalice:{code}:{request.analysis_type}"
        # redis_client.setex(cache_key, 86400, json.dumps(ai_result, ensure_ascii=False))
        
        return {
            "success": True,
            "data": ai_result,
            "source": "OpenAlice",
            "timestamp": datetime.now().isoformat(),
            "model": "Claude-3.5-Sonnet"
        }
        
    except requests.exceptions.Timeout:
        logger.error("OpenAlice 请求超时")
        return {
            "success": False,
            "error": "OpenAlice 分析超时（网络延迟高）",
            "suggestion": "请检查网络连接或稍后重试"
        }
    except json.JSONDecodeError as e:
        logger.error(f"OpenAlice 返回解析失败：{e}")
        return {
            "success": False,
            "error": "AI 响应格式错误",
            "raw": content[:200] if 'content' in locals() else str(e)
        }
    except Exception as e:
        logger.error(f"OpenAlice 调用失败：{e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "OpenAlice 分析失败，建议查看其他分析模块"
        }


@router.post("/portfolio/healthcheck")
async def portfolio_healthcheck(request: OpenAliceHealthcheckRequest):
    """
    持仓健康检查
    调用 OpenAlice 的 Guard 机制进行风险评估
    """
    if not request.holdings or len(request.holdings) == 0:
        raise HTTPException(status_code=400, detail="请提供持仓数据")
    
    try:
        # 构建持仓检查 Prompt
        holdings_str = "\n".join([
            f"- {h.get('code', '')}: 数量{h.get('qty', 0)}, 成本{h.get('cost', 0)}"
            for h in request.holdings
        ])
        
        prompt = f"""分析以下 A 股持仓的风险暴露：
{holdings_str}

请分析：
1. 行业集中度风险
2. 个股波动风险
3. 建议仓位调整

输出 JSON 格式。"""
        
        response = requests.post(
            f"{OPENALICE_MCP_URL}/v1/chat/completions",
            json={
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=OPENALICE_TIMEOUT
        )
        
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        return {
            "success": True,
            "data": {"analysis": content},
            "source": "OpenAlice"
        }
        
    except Exception as e:
        logger.error(f"持仓检查失败：{e}")
        return {"success": False, "error": str(e)}


@router.get("/market/summary")
async def market_summary():
    """
    获取 OpenAlice 生成的市场摘要
    """
    try:
        prompt = """生成今日 A 股市场摘要（100 字以内）"""
        
        response = requests.post(
            f"{OPENALICE_MCP_URL}/v1/chat/completions",
            json={
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": 200
            },
            timeout=30
        )
        
        result = response.json()
        summary = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        return {
            "success": True,
            "data": {"summary": summary},
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"市场摘要获取失败：{e}")
        return {"success": False, "error": str(e)}


@router.get("/config")
async def get_openalice_config():
    """获取 OpenAlice 配置信息（用于前端显示）"""
    return {
        "mcp_url": OPENALICE_MCP_URL,
        "web_url": OPENALICE_WEB_URL,
        "timeout": OPENALICE_TIMEOUT,
        "model": "Claude-3.5-Sonnet",
        "features": ["analyze", "healthcheck", "market_summary"]
    }
