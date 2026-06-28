"""
API 路由 - 缠论技术分析（基于 chan.py 替代实现）
"""
import datetime
import logging
import sqlite3
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Query

logger = logging.getLogger('chanlun_route')
router = APIRouter(prefix="/api/v1/chanlun", tags=["缠论分析"])

# ── 数据库路径 ──
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))

# ── chanlun-pro 适配层 ──
import sys
_CLP_SRC = str(BASE_DIR.parent / "chanlun-vendors" / "chanlun-pro" / "src")
if _CLP_SRC not in sys.path:
    sys.path.insert(0, _CLP_SRC)

from chanlun.cl import CL

def fetch_klines(symbol: str, days: int = 365, freq: str = "d") -> pd.DataFrame:
    """从缓存读取 K 线数据（支持日线和分钟线）"""
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        period_map = {
            "d": "daily", "w": "weekly", "m": "monthly",
            "15m": "15min", "30m": "30min", "60m": "60min",
        }
        db_period = period_map.get(freq, "daily")
        
        if db_period == "daily":
            # 日线优先用 stock_daily（前复权数据更完整）
            sql = """
                SELECT date, open, high, low, close, volume, turnover as amount
                FROM stock_daily
                WHERE symbol = ?
                ORDER BY date DESC
                LIMIT ?
            """
            rows = conn.execute(sql, (symbol, days)).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
            
            # 回退到 kline_cache
            sql = """
                SELECT trade_date as date, open, high, low, close, volume, amount
                FROM kline_cache
                WHERE symbol = ? AND period = ?
                ORDER BY trade_date DESC
                LIMIT ?
            """
            rows = conn.execute(sql, (symbol, db_period, days)).fetchall()
        else:
            # 分钟线从 kline_cache 读取
            sql = """
                SELECT trade_date as date, open, high, low, close, volume, amount
                FROM kline_cache
                WHERE symbol = ? AND period = ? AND source = 'akshare'
                ORDER BY trade_date DESC
                LIMIT ?
            """
            rows = conn.execute(sql, (symbol, db_period, days * 4)).fetchall()
        
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    finally:
        conn.close()


def _decode_config(cl_config: dict) -> dict:
    """前端传入配置转内部格式"""
    return cl_config or {}


# ── 原始 cl.py 子进程计算结果（与适配器隔离）──
_ORIG_CL_SRC = str(BASE_DIR.parent / "chanlun-vendors" / "chanlun-pro" / "orig_cl")

def _run_orig_cl_subprocess(symbol: str, df: pd.DataFrame, freq: str) -> dict:
    """在子进程中用原始 cl.py 计算，返回结果字典"""
    import os, json, subprocess

    # 把 K 线数据序列化为 JSON 传给子进程
    klines_json = df.to_json(orient='records', date_format='iso')

    script = '''
import sys, json
sys.path.insert(0, "''' + _ORIG_CL_SRC + '''")

from chanlun import cl
import pandas as pd

klines = json.loads("""''' + klines_json + '''""")
df = pd.DataFrame(klines)
df['date'] = pd.to_datetime(df['date'])

cd = cl.CL("''' + symbol + '''", "''' + freq + '''")
cd = cd.process_klines(df)

bis = cd.get_bis()
xds = cd.get_xds()
zss = cd.get_bi_zss()

result = {
    "bi_count": len(bis), "xd_count": len(xds), "zs_count": len(zss),
    "bis": [{"index": b.index, "type": b.type, "high": round(b.high,2), "low": round(b.low,2),
             "start_time": str(b.start.k.date)[:10] if hasattr(b, 'start') and hasattr(b.start, 'k') and hasattr(b.start.k, 'date') else str(b.start.k.date)[:10] if hasattr(b, 'start') and hasattr(b.start, 'k') else None,
             "end_time": str(b.end.k.date)[:10] if hasattr(b, 'end') and hasattr(b.end, 'k') and hasattr(b.end.k, 'date') else None,
            } for b in bis],
    "xds": [{"index": x.index, "type": x.type, "high": round(x.high,2), "low": round(x.low,2),
             "start_time": str(x.start.k.date)[:10] if hasattr(x, 'start') and hasattr(x.start, 'k') and hasattr(x.start.k, 'date') else None,
             "end_time": str(x.end.k.date)[:10] if hasattr(x, 'end') and hasattr(x.end, 'k') and hasattr(x.end.k, 'date') else None,
            } for x in xds],
    "zss": [{"index": z.index, "zg": round(z.zg,2), "zd": round(z.zd,2), "gg": round(z.gg,2), "dd": round(z.dd,2)} for z in zss],
}
print(json.dumps(result))
'''

    script_path = os.path.join(BASE_DIR, '.orig_run.py')
    with open(script_path, 'w') as f:
        f.write(script)

    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=60,
            cwd=BASE_DIR,
        )
        if proc.returncode != 0:
            logger.error(f"原始cl.py出错: {proc.stderr[:500]}")
            return None
        # 从 stdout 提取 JSON
        out = proc.stdout
        idx = out.find('{')
        if idx >= 0:
            return json.loads(out[idx:])
        logger.error(f"原始cl.py无JSON输出: {out[:200]}")
        return None
    except subprocess.TimeoutExpired:
        logger.error("原始cl.py计算超时")
        return None
    except Exception as e:
        logger.error(f"原始cl.py异常: {e}")
        return None
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def _get_fx_time(fx) -> str:
    """从 FX 对象提取时间字符串，占位符日期返回 None"""
    try:
        if hasattr(fx, 'k') and hasattr(fx.k, 'date'):
            d = fx.k.date
            dt_str = str(d)[:19] if hasattr(d, 'strftime') else str(d)[:10]
            if '2000' in dt_str or '0001' in dt_str:
                return None
            return dt_str
        if hasattr(fx, 'time') and fx.time:
            return str(fx.time)[:19]
    except Exception:
        pass
    return None


def _run_cl(symbol: str, df: pd.DataFrame, freq: str, config_extra: dict = None) -> dict:
    """用 CL 计算一次并返回笔/线段/中枢的列表"""
    cd = CL(symbol, freq, config=config_extra or {})
    cd.process_klines(df)

    bis = cd.get_bis()
    xds = cd.get_xds()
    bi_zss = cd.get_bi_zss()

    bi_list = [{
        "index": bi.index, "type": bi.type,
        "high": round(float(bi.high), 2) if hasattr(bi, 'high') else 0,
        "low": round(float(bi.low), 2) if hasattr(bi, 'low') else 0,
        "start_time": getattr(bi, '_start_time', None),
        "end_time": getattr(bi, '_end_time', None),
    } for bi in bis]

    xd_list = [{
        "index": xd.index, "type": xd.type,
        "high": round(float(xd.high), 2) if hasattr(xd, 'high') else 0,
        "low": round(float(xd.low), 2) if hasattr(xd, 'low') else 0,
        "start_time": getattr(xd, '_start_time', None),
        "end_time": getattr(xd, '_end_time', None),
    } for xd in xds]

    # 为中枢推算起止时间：找到与中枢重叠的笔，取最早起始和最晚结束
    def _zs_time_range(zs):
        """从 BIs 中推算中枢的起止时间"""
        try:
            if not hasattr(zs, 'zg') or not zs.zg:
                return None, None
            zs_high = float(zs.zg)
            zs_low = float(zs.zd)
            st, et = None, None
            for bi in bis:
                if hasattr(bi, 'high') and hasattr(bi, 'low'):
                    bi_high = float(bi.high)
                    bi_low = float(bi.low)
                    # 笔与中枢重叠：笔的范围与中枢范围有交集
                    if bi_high >= zs_low and bi_low <= zs_high:
                        bs = getattr(bi, '_start_time', None)
                        be = getattr(bi, '_end_time', None)
                        bs_norm = bs.replace('/', '-')[:10] if bs else None
                        be_norm = be.replace('/', '-')[:10] if be else None
                        if bs_norm and (st is None or bs_norm < st):
                            st = bs_norm
                        if be_norm and (et is None or be_norm > et):
                            et = be_norm
            return st, et
        except Exception:
            return None, None

    zs_list = [{
        "index": zs.index,
        "zg": round(float(zs.zg), 2) if zs.zg else 0,
        "zd": round(float(zs.zd), 2) if zs.zd else 0,
        "gg": round(float(zs.gg), 2) if zs.gg else 0,
        "dd": round(float(zs.dd), 2) if zs.dd else 0,
        "start_time": _get_fx_time(zs.start) if hasattr(zs, 'start') and zs.start else None,
        "end_time": _get_fx_time(zs.end) if hasattr(zs, 'end') and zs.end else None,
    } for zs in bi_zss]
    # 用推算的时间覆盖占位符（2000年或空）
    for i, zs in enumerate(bi_zss):
        exist_st = zs_list[i].get('start_time', '')
        exist_et = zs_list[i].get('end_time', '')
        is_placeholder = not exist_st or exist_st.startswith('2000') or '2000' in exist_st
        if is_placeholder or not exist_et or exist_et.startswith('2000') or '2000' in exist_et:
            st, et = _zs_time_range(zs)
            if is_placeholder and st:
                zs_list[i]['start_time'] = st
            if (not exist_et or exist_et.startswith('2000') or '2000' in exist_et) and et:
                zs_list[i]['end_time'] = et

    return {
        "label": "",
        "bi_count": len(bi_list),
        "xd_count": len(xd_list),
        "zs_count": len(zs_list),
        "bis": bi_list,
        "xds": xd_list,
        "zss": zs_list,
    }


@router.get("/compare/{symbol}")
async def compare_chanlun(
    symbol: str,
    freq: str = Query("d", description="周期"),
    days: int = Query(365, ge=60, le=2000),
):
    """三个缠论参数配置同时计算结果对比
    
    - algo1: 严格（分型不包含, 红色实线）
    - algo2: 宽松（分型可包含, 绿色虚线）
    - algo3: 极严（不允许次高低, 蓝色点线）
    """
    df = fetch_klines(symbol, days, freq)
    if df is None or len(df) == 0:
        return {"status": "error", "message": f"未找到 {symbol} 的 K 线数据"}

    # 算法1: 严格（分型不包含）
    algo1 = _run_cl(symbol, df, freq, {})
    algo1["label"] = "严格"

    # 算法2: 宽松（分型可包含，次高低成笔）
    algo2 = _run_cl(symbol, df, freq, {"fx_bh": "dingdi", "bi_fx_cgd": True})
    algo2["label"] = "宽松"

    # 算法3: 极严
    algo3 = _run_cl(symbol, df, freq, {
        "fx_bh": "diding",
        "bi_fx_cgd": False,
        "bi_allow_sub_peak": False,
        "bi_strict": True,
    })
    algo3["label"] = "极严"

    # 算法4: ChanlunX (C++通达信插件移植)
    from chanlunx_algo import chanlunx_analyze
    highs = df['high'].tolist()
    lows = df['low'].tolist()
    dates = df['date'].tolist()
    clx_bis, _, clx_zss = chanlunx_analyze(highs, lows)
    clx_bi_list = []
    for i, b in enumerate(clx_bis):
        # 计算每笔的 high/low
        bi_high = b.gao
        bi_low = b.di
        bi_type = 'up' if b.fangXiang == 1 else 'down'
        start_time = str(dates[b.kaiShi])[:10] if b.kaiShi < len(dates) else None
        end_time = str(dates[min(b.jieShu, len(dates)-1)])[:10] if b.jieShu < len(dates) else None
        clx_bi_list.append({
            "index": i, "type": bi_type,
            "high": round(float(bi_high), 2),
            "low": round(float(bi_low), 2),
            "start_time": start_time,
            "end_time": end_time,
        })
    # 为 ChanlunX 中枢推算起止时间
    def _zs_range_for_clx(zs_dict):
        try:
            zg = zs_dict.get('zg', 0)
            zd = zs_dict.get('zd', 0)
            st, et = None, None
            for b in clx_bi_list:
                if b['high'] >= zd and b['low'] <= zg:
                    if b['start_time'] and (st is None or b['start_time'] < st):
                        st = b['start_time']
                    if b['end_time'] and (et is None or b['end_time'] > et):
                        et = b['end_time']
            return st, et
        except:
            return None, None
    clx_zs_list = []
    for zs_d in clx_zss:
        zs_copy = dict(zs_d)
        st, et = _zs_range_for_clx(zs_copy)
        zs_copy['start_time'] = st
        zs_copy['end_time'] = et
        clx_zs_list.append(zs_copy)
    algo4 = {
        "label": "ChanlunX",
        "bi_count": len(clx_bi_list),
        "xd_count": 0,
        "zs_count": len(clx_zs_list),
        "bis": clx_bi_list,
        "xds": [],
        "zss": clx_zs_list,
    }

    # 原始 K 线（分钟级用 Unix 时间戳，日线用 YYYY-MM-DD）
    is_minute = freq.endswith('m') and freq != 'm'
    kline_data = []
    for _, row in df.iterrows():
        dt = row['date']
        if is_minute:
            # 分钟级：Unix 时间戳（秒）
            import time as _time_mod
            if hasattr(dt, 'timestamp'):
                t = int(dt.timestamp())
            else:
                t = int(_time_mod.mktime(dt.timetuple())) if hasattr(dt, 'timetuple') else str(dt)[:19]
        else:
            t = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)[:10]
        kline_data.append({
            "time": t,
            "open": round(float(row['open']), 2),
            "high": round(float(row['high']), 2),
            "low": round(float(row['low']), 2),
            "close": round(float(row['close']), 2),
            "volume": int(row['volume']),
        })

    return {
        "status": "ok",
        "symbol": symbol,
        "frequency": freq,
        "klines": kline_data,
        "klines_count": len(kline_data),
        "algorithms": [a for a in [algo1, algo2, algo3, algo4] if a is not None],
    }


@router.get("/analyze/{symbol}")
async def analyze_chanlun(
    symbol: str,
    freq: str = Query("d", description="周期: d/w/m/60m/30m/15m/5m/1m"),
    days: int = Query(365, ge=60, le=2000, description="回溯天数"),
    with_detail: bool = Query(False, description="返回详细数据"),
):
    """缠论分析：笔、线段、中枢、买卖点"""
    df = fetch_klines(symbol, days, freq)
    if df is None or len(df) == 0:
        return {"status": "error", "message": f"未找到 {symbol} 的 K 线数据"}

    # 创建适配器
    cd = CL(symbol, freq)
    cd.process_klines(df)

    # 提取结果
    bis = cd.get_bis()
    xds = cd.get_xds()
    bi_zss = cd.get_bi_zss()
    idx = cd.get_idx()

    # 笔（含时间戳用于前端画图定位）
    bi_list = []
    for bi in bis:
        bi_list.append({
            "index": bi.index,
            "type": bi.type,
            "high": round(float(bi.high), 2) if hasattr(bi, 'high') else 0,
            "low": round(float(bi.low), 2) if hasattr(bi, 'low') else 0,
            "start_time": getattr(bi, '_start_time', None),
            "end_time": getattr(bi, '_end_time', None),
        })

    # 线段（含时间戳）
    xd_list = []
    for xd in xds:
        xd_list.append({
            "index": xd.index,
            "type": xd.type,
            "high": round(float(xd.high), 2) if hasattr(xd, 'high') else 0,
            "low": round(float(xd.low), 2) if hasattr(xd, 'low') else 0,
            "start_time": getattr(xd, '_start_time', None),
            "end_time": getattr(xd, '_end_time', None),
        })

    # 中枢
    zs_list = []
    for zs in bi_zss:
        zs_list.append({
            "index": zs.index,
            "zg": round(float(zs.zg), 2) if zs.zg else 0,
            "zd": round(float(zs.zd), 2) if zs.zd else 0,
            "gg": round(float(zs.gg), 2) if zs.gg else 0,
            "dd": round(float(zs.dd), 2) if zs.dd else 0,
        })

    result = {
        "status": "ok",
        "symbol": symbol,
        "frequency": freq,
        "klines_count": len(df),
        "date_range": {
            "start": str(df['date'].iloc[0]) if len(df) > 0 else None,
            "end": str(df['date'].iloc[-1]) if len(df) > 0 else None,
        },
        "bi_count": len(bi_list),
        "xd_count": len(xd_list),
        "zs_count": len(zs_list),
    }

    if with_detail:
        # MACD 最后 10 个值
        macd = {}
        if 'macd' in idx:
            macd = {
                "dea": [round(v, 2) for v in idx['macd']['dea'][-10:]],
                "dif": [round(v, 2) for v in idx['macd']['dif'][-10:]],
                "hist": [round(v, 2) for v in idx['macd']['hist'][-10:]],
            }
        # 原始 K 线数据 (用于前端画图)
        kline_data = []
        for _, row in df.iterrows():
            dt = row['date']
            if hasattr(dt, 'strftime'):
                dt_str = dt.strftime('%Y-%m-%d')
            else:
                dt_str = str(dt)[:10]
            kline_data.append({
                "time": dt_str,
                "open": round(float(row['open']), 2),
                "high": round(float(row['high']), 2),
                "low": round(float(row['low']), 2),
                "close": round(float(row['close']), 2),
                "volume": int(row['volume']),
            })
        result.update({
            "detail": True,
            "macd": macd,
            "klines": kline_data,
            "bis": bi_list,
            "xds": xd_list,
            "zss": zs_list,
        })

    return result


@router.get("/signals/{symbol}")
async def chanlun_signals(
    symbol: str,
    freq: str = Query("d", description="周期"),
    days: int = Query(365, ge=60, le=2000),
):
    """缠论买卖点信号"""
    df = fetch_klines(symbol, days, freq)
    if df is None or len(df) == 0:
        return {"status": "error", "message": f"未找到 {symbol} 的 K 线数据"}

    cd = CL(symbol, freq)
    cd.process_klines(df)

    bis = cd.get_bis()
    last_bi = bis[-1] if bis else None

    signals = {
        "status": "ok",
        "symbol": symbol,
        "frequency": freq,
        "last_bi_type": last_bi.type if last_bi else None,
        "bi_count": len(bis),
        "xd_count": len(cd.get_xds()),
        "zs_count": len(cd.get_bi_zss()),
        "trend": "up" if bis and bis[-1].type == "up" else "down" if bis else "unknown",
    }

    return signals
