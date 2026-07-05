"""
A股数据采集 — 共享工具：东财防封限流、TDX 连接、前缀映射
"""
import json, re, random, time, socket
from datetime import datetime
from typing import Optional
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# ── 全局常量 ──
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"
EM_MIN_INTERVAL = 1.2       # 东财最小请求间隔(秒)
_em_last_call = 0.0

# ── 东财防封：全局串行限流 + 会话复用 ──
_em_session: Optional[requests.Session] = None


def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: float = 15, max_retries: int = 3) -> requests.Response:
    """
    东财统一请求入口：
    - 串行限流（最小间隔 + 随机抖动）
    - 会话复用（Keep-Alive）
    - 自动重试（429/5xx 指数退避）
    - 403 不重试（用降频应对）
    """
    global _em_last_call, _em_session
    now = time.time()
    elapsed = now - _em_last_call
    sleep_time = EM_MIN_INTERVAL + random.uniform(0, 0.3) - elapsed
    if sleep_time > 0:
        time.sleep(sleep_time)

    if _em_session is None:
        _em_session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        _em_session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
        _em_session.mount("http://", HTTPAdapter(max_retries=retry_strategy))

    if headers is None:
        headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    else:
        headers.setdefault("User-Agent", UA)

    resp = _em_session.get(url, params=params, headers=headers, timeout=timeout)
    _em_last_call = time.time()
    return resp


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 100,
                         sort_columns: str = "", sort_types: str = "") -> list[dict]:
    """东财数据中心统一查询"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": report_name,
        "columns": columns,
        "pageNumber": 1,
        "pageSize": min(page_size, 500),
        "sortTypes": sort_types,
        "sortColumns": sort_columns,
        "source": "WEB",
        "client": "WEB",
    }
    if filter_str:
        params["filter"] = filter_str

    try:
        r = em_get(url, params=params)
        data = r.json()
        if data.get("success") and data.get("result", {}).get("data"):
            return data["result"]["data"]
    except Exception as e:
        print(f"[WARN] eastmoney_datacenter {report_name}: {e}")
    return []


# ── TDX 客户端（兼容 mootdx 0.10/0.11） ──
TDX_SERVERS = [
    ("180.153.18.170", 7709), ("180.153.18.171", 7709), ("119.147.212.81", 7709),
    ("40.73.87.86", 7709), ("112.74.214.43", 7709),
]


def _probe(ip: str, port: int, timeout: float = 1.5) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def tdx_client(market: str = "std"):
    """获取可用的 mootdx Quotes 客户端，三级 fallback"""
    from mootdx.quotes import Quotes

    # 先 TCP 探测
    for ip, port in TDX_SERVERS:
        if _probe(ip, port):
            try:
                return Quotes.factory(market=market, server=(ip, port), timeout=5, multithread=True)
            except Exception:
                continue

    # fallback 1: 裸 factory（可能吃 BESTIP 空串崩溃）
    try:
        return Quotes.factory(market=market)
    except Exception:
        pass

    # fallback 2: 逐个 IP 尝试
    for ip, port in TDX_SERVERS:
        try:
            return Quotes.factory(market=market, server=(ip, port))
        except Exception:
            continue
    raise RuntimeError("无法连接任何 TDX 服务器")


# ── 股票前缀映射 ──

def get_prefix(code: str) -> str:
    """根据代码判断市场前缀"""
    if code.startswith("6") or code.startswith("688"):
        return "SH"
    elif code.startswith("0") or code.startswith("3") or code.startswith("2"):
        return "SZ"
    elif code.startswith("4") or code.startswith("8"):
        return "BJ"
    return "SZ"


def get_full_code(code: str) -> str:
    """补全为带前缀的全码"""
    if "." in code:
        return code  # 已是全码
    return f"{get_prefix(code)}.{code}"


# ── 日期工具 ──

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def today_ymd() -> str:
    """YYYYMMDD 格式"""
    return datetime.now().strftime("%Y%m%d")
