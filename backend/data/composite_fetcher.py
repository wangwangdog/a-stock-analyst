"""
三源数据获取器：Baostock 主 + mootdx 降级 + 腾讯补齐

策略优先级：
1. Baostock：历史日线主数据源（OHLCV 完整）
2. mootdx：Baostock 降级方案（TCP 通达信协议，实时性强）
3. 腾讯财经：当日收盘后数据补齐（如果前两者当日数据缺失）
"""

import pandas as pd
from typing import Optional
from datetime import date
from loguru import logger

# ── 导入数据源 ──
try:
    from .baostock_fetcher import (
        available as bs_available,
        get_daily_kline as bs_get_kline,
    )
except ImportError:
    bs_available = lambda: False
    bs_get_kline = None

try:
    from .mootdx_fetcher import (
        available as mootdx_available,
        get_klines_df as mootdx_get_kline,
    )
except ImportError:
    mootdx_available = lambda: False
    mootdx_get_kline = None

try:
    from .tencent_quote import fetch_one as tencent_fetch
except ImportError:
    tencent_fetch = None


def available() -> bool:
    """检查是否至少有一个数据源可用"""
    return bs_available() or mootdx_available() or (tencent_fetch is not None)


def get_daily_kline(
    symbol: str,
    start_date: str = None,
    end_date: str = None,
    use_mootdx_fallback: bool = True,
    use_tencent_fallback: bool = True,
) -> Optional[pd.DataFrame]:
    """
    获取日 K 线（前复权）。

    策略：
    1. 优先 Baostock（历史数据完整，含成交量）
    2. 降级 mootdx（TCP 通达信协议，实时性强，适合当日数据）
    3. 腾讯补齐：当日收盘后数据补齐（如果前两者当日数据缺失）

    Args:
        symbol: 股票代码，如 "000001"
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"，默认今天
        use_mootdx_fallback: 是否启用 mootdx 降级（默认 True）
        use_tencent_fallback: 是否启用腾讯补齐（默认 True）

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, volume, amount, turnover
    """
    today = date.today().strftime("%Y-%m-%d")
    
    # 1. 尝试 Baostock（历史数据主源）
    if bs_get_kline and bs_available():
        df = bs_get_kline(symbol, start_date, end_date)
        if df is not None and not df.empty:
            logger.debug(f"[Baostock] {symbol}: {len(df)} 条")
            
            # 检查是否需要补齐当日（收盘后）
            if end_date is None or end_date == today:
                if 'trade_date' in df.columns:
                    latest_date = df['trade_date'].max()
                    if latest_date != today and use_tencent_fallback:
                        # 尝试用腾讯补齐当日
                        tencent_df = _fetch_tencent_today(symbol)
                        if tencent_df is not None:
                            df = df[df['trade_date'] != today]
                            df = pd.concat([df, tencent_df], ignore_index=True)
                            logger.info(f"[腾讯补齐] {symbol} 当日 ({today}) 已补全")
            
            return df
    
    # 2. Baostock 不可用，降级到 mootdx
    if use_mootdx_fallback and mootdx_get_kline and mootdx_available():
        try:
            # mootdx 参数：category=4 为日线，offset=100 拉取最近 100 条
            # 可根据 start_date 调整 offset
            offset = 100
            if start_date:
                # 粗略估算 offset（交易日约 240 天/年）
                from datetime import datetime
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(today, "%Y-%m-%d")
                    days = (end_dt - start_dt).days
                    offset = min(days + 30, 500)  # 最多拉 500 条，预留缓冲
                except:
                    pass
            
            df = mootdx_get_kline(symbol, category=4, offset=offset)
            if df is not None and not df.empty:
                # mootdx 返回的 DataFrame 列名可能需要标准化
                # mootdx 列名：datetime, open, close, high, low, vol, amount
                df = _normalize_mootdx_df(df, symbol)
                logger.info(f"[mootdx 降级] {symbol}: {len(df)} 条")
                
                # 检查是否需要腾讯补齐当日
                if end_date is None or end_date == today:
                    if 'trade_date' in df.columns:
                        latest_date = df['trade_date'].max()
                        if latest_date != today and use_tencent_fallback:
                            tencent_df = _fetch_tencent_today(symbol)
                            if tencent_df is not None:
                                df = df[df['trade_date'] != today]
                                df = pd.concat([df, tencent_df], ignore_index=True)
                                logger.info(f"[腾讯补齐] {symbol} 当日 ({today}) 已补全")
                
                return df
        except Exception as e:
            logger.warning(f"[mootdx] {symbol} 获取失败：{e}")
    
    # 3. mootdx 也不可用，尝试腾讯（仅当日）
    if tencent_fetch and use_tencent_fallback and end_date is None:
        tencent_df = _fetch_tencent_today(symbol)
        if tencent_df is not None:
            logger.info(f"[腾讯降级] {symbol} 使用腾讯实时数据（无历史）")
            return tencent_df
    
    return None


def _normalize_mootdx_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    标准化 mootdx 返回的 DataFrame 列名
    mootdx: datetime, open, close, high, low, vol, amount
    目标：trade_date, open, high, low, close, volume, amount, turnover
    """
    if df is None:
        return None
    
    try:
        # 复制避免修改原数据
        df = df.copy()
        
        # 列名映射
        if 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'trade_date'})
        if 'vol' in df.columns:
            df = df.rename(columns={'vol': 'volume'})
        
        # 添加缺失的 turnover 列（mootdx 无换手率）
        if 'turnover' not in df.columns:
            df['turnover'] = 0.0
        
        # 确保列顺序一致
        expected_cols = ['trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = 0
        
        # 转换为字符串日期格式（如果 datetime 是对象）
        if 'trade_date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['trade_date']):
            df['trade_date'] = df['trade_date'].dt.strftime('%Y-%m-%d')
        
        return df[expected_cols]
    except Exception as e:
        logger.error(f"[mootdx 标准化] {symbol} 失败：{e}")
        return None


def _fetch_tencent_today(symbol: str) -> Optional[pd.DataFrame]:
    """从腾讯获取当日实时数据，转换为 K 线格式"""
    if tencent_fetch is None:
        return None

    try:
        data = tencent_fetch(symbol)
        if data is None:
            return None

        today = date.today().strftime("%Y-%m-%d")

        # 腾讯返回字段映射到标准 K 线格式
        kline = {
            "trade_date": today,
            "open": data.get("open", 0),
            "high": data.get("high", 0),
            "low": data.get("low", 0),
            "close": data.get("price", 0),  # 当前价作为收盘价
            "volume": 0,  # 腾讯无绝对成交量
            "amount": data.get("amount_wan", 0) * 10000,  # 万元转元
            "turnover": data.get("turnover_pct", 0),  # 换手率
        }

        return pd.DataFrame([kline])
    except Exception as e:
        logger.warning(f"[腾讯] 获取 {symbol} 失败：{e}")
        return None


def get_real_time_quote(symbol: str) -> Optional[dict]:
    """获取实时行情（仅腾讯，含 PE/PB/市值）"""
    if tencent_fetch is None:
        return None
    try:
        return tencent_fetch(symbol)
    except:
        return None


def get_stock_list() -> pd.DataFrame:
    """获取股票列表（优先 Baostock）"""
    if bs_get_kline and bs_available():
        from .baostock_fetcher import get_stock_list as bs_get_list
        return bs_get_list()
    return pd.DataFrame()


# ── 批量优化 ──

def batch_get_kline(
    symbols: list[str],
    start_date: str = None,
    end_date: str = None,
    max_workers: int = 10,
) -> dict:
    """批量获取 K 线（多线程）"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(get_daily_kline, sym, start_date, end_date): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                logger.error(f"[批量] {sym} 失败：{e}")
                results[sym] = None
    return results
