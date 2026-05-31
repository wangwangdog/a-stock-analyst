"""
Kronos 金融预测引擎
https://github.com/shiyu-coder/Kronos
"""
import sys
import os
import torch
import pandas as pd
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# 添加 Kronos 模型路径
KRONOS_PATH = Path("/home/dogzi/.openclaw/workspace/kronos-ai")
sys.path.insert(0, str(KRONOS_PATH))

from model import Kronos, KronosTokenizer, KronosPredictor

router = APIRouter(prefix="/api/v1/kronos", tags=["Kronos 预测"])

# 全局模型缓存
_model_cache: dict = {}


def get_model(model_name: str = "kronos-small") -> KronosPredictor:
    """懒加载模型，全局单例"""
    if model_name not in _model_cache:
        print(f"[Kronos] 正在加载模型：{model_name}...")
        
        # 模型映射
        model_mapping = {
            "kronos-mini": {
                "tokenizer": "NeoQuasar/Kronos-Tokenizer-2k",
                "model": "NeoQuasar/Kronos-mini",
                "max_context": 2048
            },
            "kronos-small": {
                "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
                "model": "NeoQuasar/Kronos-small",
                "max_context": 512
            },
            "kronos-base": {
                "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
                "model": "NeoQuasar/Kronos-base",
                "max_context": 512
            }
        }
        
        if model_name not in model_mapping:
            raise ValueError(f"不支持的模型：{model_name}")
        
        config = model_mapping[model_name]
        
        # 加载 Tokenizer
        tokenizer = KronosTokenizer.from_pretrained(config["tokenizer"])
        
        # 加载模型
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = Kronos.from_pretrained(config["model"])
        model = model.to(device)
        model.eval()
        
        # 创建 Predictor
        predictor = KronosPredictor(
            model=model,
            tokenizer=tokenizer,
            device=device,
            max_context=config["max_context"]
        )
        
        _model_cache[model_name] = predictor
        print(f"[Kronos] 模型加载完成：{model_name} @ {device}")
    
    return _model_cache[model_name]


class KronosPredictRequest(BaseModel):
    """Kronos 预测请求"""
    symbol: str = Field(..., description="股票代码，如 000001")
    lookback: int = Field(default=200, ge=1, le=1000, description="历史窗口长度")
    pred_len: int = Field(default=20, ge=1, le=100, description="预测长度（交易日）")
    model: str = Field(default="kronos-small", description="模型选择")
    T: float = Field(default=1.0, ge=0.1, le=2.0, description="采样温度")
    top_p: float = Field(default=0.9, ge=0.1, le=1.0, description="Top-p 采样")
    sample_count: int = Field(default=1, ge=1, le=10, description="采样数量（用于置信度区间）")


class KronosPredictResponse(BaseModel):
    """Kronos 预测响应"""
    symbol: str
    historical: list[dict]
    prediction: list[dict]
    model: str
    device: str
    lookback: int
    pred_len: int
    T: float
    top_p: float
    sample_count: int


@router.get("/models")
async def list_models():
    """获取可用模型列表"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "models": [
                {
                    "name": "kronos-mini",
                    "params": "4.1M",
                    "context": 2048,
                    "description": "轻量级模型，适合快速预测"
                },
                {
                    "name": "kronos-small",
                    "params": "24.7M",
                    "context": 512,
                    "description": "推荐模型，平衡速度与精度"
                },
                {
                    "name": "kronos-base",
                    "params": "102.3M",
                    "context": 512,
                    "description": "高精度模型，适合复杂分析"
                }
            ]
        }
    }


@router.post("/predict")
async def predict(request: KronosPredictRequest):
    """单只股票预测"""
    try:
        # 1. 加载数据
        db_path = Path("/home/dogzi/.openclaw/workspace/a-stock-analyst/backend/data/stock_cache.db")
        if not db_path.exists():
            raise HTTPException(500, "数据库文件不存在")
        
        conn = sqlite3.connect(db_path)
        
        # 查询历史数据（需要 lookback + pred_len 用于时间戳对齐）
        sql = f"""
            SELECT trade_date, open, high, low, close, volume, amount 
            FROM stock_daily 
            WHERE symbol = '{request.symbol}'
            ORDER BY trade_date DESC 
            LIMIT {request.lookback + request.pred_len}
        """
        
        df = pd.read_sql(sql, conn)
        conn.close()
        
        if df.empty or len(df) < request.lookback:
            raise HTTPException(404, f"数据不足：{request.symbol} 历史数据少于 {request.lookback} 天")
        
        # 2. 数据预处理
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['timestamps'] = pd.to_datetime(df['trade_date'])
        
        # 准备输入数据（Kronos 需要的特征：open, high, low, close, volume, amount）
        feature_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
        x_df = df.iloc[:request.lookback][feature_cols].copy()
        x_ts = df.iloc[:request.lookback]['timestamps']
        y_ts = df.iloc[request.lookback:request.lookback+request.pred_len]['timestamps']
        
        # 3. 加载模型并预测
        predictor = get_model(request.model)
        
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=request.pred_len,
            T=request.T,
            top_p=request.top_p,
            sample_count=request.sample_count,
            verbose=False
        )
        
        # 4. 格式化输出
        # 最近 100 根 K 线作为历史参考
        historical = df.iloc[-100:].to_dict('records')
        
        # 预测结果（包含 OHLCV + 时间戳）
        prediction = []
        for _, row in pred_df.iterrows():
            prediction.append({
                "date": row.get("timestamps", "") if hasattr(row, "timestamps") else "",
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
                "amount": float(row.get("amount", 0))
            })
        
        return KronosPredictResponse(
            symbol=request.symbol,
            historical=historical,
            prediction=prediction,
            model=request.model,
            device=str(predictor.device),
            lookback=request.lookback,
            pred_len=request.pred_len,
            T=request.T,
            top_p=request.top_p,
            sample_count=request.sample_count
        )
        
    except Exception as e:
        raise HTTPException(500, f"Kronos 预测失败：{str(e)}")


@router.post("/batch-predict")
async def batch_predict(request: dict):
    """批量预测（选股后筛选）"""
    symbols = request.get("symbols", [])
    if not symbols or len(symbols) == 0:
        raise HTTPException(400, "symbols 不能为空")
    
    if len(symbols) > 50:
        raise HTTPException(400, "单次批量预测不超过 50 只股票")
    
    lookback = request.get("lookback", 200)
    pred_len = request.get("pred_len", 10)
    model = request.get("model", "kronos-small")
    
    results = {}
    for symbol in symbols:
        try:
            # 复用单只预测逻辑
            req = KronosPredictRequest(
                symbol=symbol,
                lookback=lookback,
                pred_len=pred_len,
                model=model,
                sample_count=1  # 批量预测只用 1 个采样
            )
            result = await predict(req)
            results[symbol] = {
                "code": 0,
                "prediction": result.prediction,
                "close_price": result.prediction[-1]["close"] if result.prediction else 0
            }
        except Exception as e:
            results[symbol] = {"code": -1, "error": str(e)}
    
    return {
        "code": 0,
        "data": results
    }
