"""
Lean 风格数据下载器（数据源采集核心层）

架构：
  IDataDownloader (接口)
       ├── StockApiDownloader   — Tencent HTTP (主源，1m/5m/日线)
       ├── MootdxDownloader     — 通达信 TCP (分钟线降级)
       ├── AkshareDownloader    — AKShare 兜底
       └── BaostockDownloader   — Baostock 兜底

  DataProvider (编排器)
       ├── get_kline()         — 日K线：cache → Tencent → AKShare → Baostock
       ├── get_minute_kline()  — 分钟K线：cache → Tencent(m1/m5) → mootdx → AKShare
       ├── need_to_download()  — 新鲜度检查 (类 Lean.NeedToDownload)
       └── download_once()     — 并发保护下载 (类 Lean.DownloadOnce)
"""

import time
import threading
from typing import Optional, Callable
from datetime import datetime, timedelta, date
from functools import wraps

import pandas as pd
from loguru import logger

# ── 数据源新鲜度 TTL ──
DEFAULT_TTL = {
    "daily": timedelta(days=1),     # 日线：1天内不用重下
    "60m":   timedelta(hours=2),    # 60分钟：2小时内
    "30m":   timedelta(hours=1),    # 30分钟：1小时内
    "15m":   timedelta(minutes=30), # 15分钟：30分钟内
    "5m":    timedelta(minutes=15), # 5分钟：15分钟内
    "1m":    timedelta(minutes=5),  # 1分钟：5分钟内
    "realtime": timedelta(seconds=30),  # 实时：30秒
}

# 周期映射：stock_api_fetcher 参数 → kline_cache period
PERIOD_MAP = {
    "1m":  "1m",   # 未来支持
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",  # 未来支持
    "60m": "60m",
    "daily": "daily",
}

# 并发下载锁 (类 Lean.DownloadOnce 的并发保护)
_download_locks: dict = {}
_download_lock_global = threading.Lock()


# ══════════════════════════════════════════════
# 接口定义 (类 Lean.IDataDownloader)
# ══════════════════════════════════════════════

class IDataDownloader:
    """数据下载器接口"""

    def available(self) -> bool:
        """数据源是否可用"""
        return False

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        """获取K线数据，返回 {trade_date, open, high, low, close, volume, amount}"""
        return None

    def name(self) -> str:
        return self.__class__.__name__


# ══════════════════════════════════════════════
# 具体下载器实现
# ══════════════════════════════════════════════

class StockApiDownloader(IDataDownloader):
    """腾讯HTTP直连（主源），支持日线和分钟线"""

    def available(self) -> bool:
        return True  # HTTP接口无需安装

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        try:
            from .stock_api_fetcher import get_daily_kline
            return get_daily_kline(symbol, start, end)
        except Exception as e:
            logger.debug(f"[StockApiDownloader] {symbol} 失败: {e}")
            return None


class StockApiMinuteDownloader(IDataDownloader):
    """腾讯分钟K线 HTTP直连，支持 1m/5m/15m/30m/60m"""

    # 腾讯API参数映射
    _PERIOD_MAP = {"5m": "m5", "15m": "m15", "30m": "m30", "60m": "m60", "1m": "m1"}

    def available(self) -> bool:
        return True

    def get_kline(self, symbol: str, period: str = "5m",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        tencent_param = self._PERIOD_MAP.get(period)
        if not tencent_param:
            return None

        try:
            # 获取股票6位代码（去前缀）
            raw_code = symbol.split(".")[-1]
            if symbol.upper().startswith(("SH.", "SH")):
                pref = "sh"
            elif symbol.upper().startswith(("SZ.", "SZ")):
                pref = "sz"
            else:
                pref = "sh" if raw_code.startswith(("6", "9")) else "sz"

            # 腾讯 mkline 接口
            import urllib.request, json
            url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},{tencent_param},,480"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            # 解析返回数据
            api_code = f"{pref}{raw_code}"
            klines = data.get("data", {}).get(api_code, {}).get(tencent_param, [])
            if not klines:
                return None

            records = []
            for item in klines:
                dt_str = str(item[0])
                td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"

                # 时间范围过滤
                if start and td[:10] < start[:10]:
                    continue
                if end and td[:10] > end[:10]:
                    continue

                records.append({
                    "trade_date": td,
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[7]) * 100_000_000 if len(item) > 7 else 0,
                    "amount": float(item[7]) * 100_000_000 if len(item) > 7 else 0,
                })

            if not records:
                return None
            df = pd.DataFrame(records)
            return df
        except Exception as e:
            logger.debug(f"[TencentMinute] {symbol} {period} 失败: {e}")
            return None


class MootdxDownloader(IDataDownloader):
    """通达信 TCP 协议降级（速度快，盘后数据）"""

    _PERIOD_MAP = {"daily": 4, "week": 5, "month": 6,
                   "1m": 7, "5m": 8, "15m": 9, "30m": 10, "60m": 11}

    def available(self) -> bool:
        try:
            from .mootdx_fetcher import available as _avail
            return _avail()
        except ImportError:
            return False

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        category = self._PERIOD_MAP.get(period)
        if not category:
            return None

        try:
            from .mootdx_fetcher import get_klines_df, _market

            # 估算需要的条数
            offset = 100
            if period == "daily":
                offset = 365
            elif period in ("60m", "30m"):
                offset = 240
            elif period in ("15m", "5m"):
                offset = 480
            elif period == "1m":
                offset = 1440

            raw_code = symbol.split(".")[-1]
            df = get_klines_df(raw_code, category=category, offset=offset)
            if df is None or df.empty:
                return None

            # 标准化列名
            df = df.copy()
            col_map = {}
            for src, dst in [("datetime", "trade_date"), ("vol", "volume")]:
                if src in df.columns:
                    col_map[src] = dst
            if col_map:
                df = df.rename(columns=col_map)

            # 确保必需列
            for col in ["trade_date", "open", "close", "high", "low"]:
                if col not in df.columns:
                    return None
            if "volume" not in df.columns:
                df["volume"] = 0
            if "amount" not in df.columns:
                df["amount"] = 0

            # 格式化日期
            if "trade_date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["trade_date"]):
                df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d %H:%M:%S" if period != "daily" else "%Y-%m-%d")

            # 过滤
            if start:
                df = df[df["trade_date"] >= start]
            if end:
                df = df[df["trade_date"] <= end]

            return df if not df.empty else None
        except Exception as e:
            logger.debug(f"[MootdxDownloader] {symbol} {period} 失败: {e}")
            return None


class AkshareDownloader(IDataDownloader):
    """AKShare 兜底"""

    def available(self) -> bool:
        try:
            from .akshare_fetcher import available as _avail
            return _avail()
        except ImportError:
            return False

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        try:
            from .akshare_fetcher import get_daily_kline
            if period != "daily":
                return None
            return get_daily_kline(symbol, start, end)
        except Exception as e:
            logger.debug(f"[AkshareDownloader] {symbol} 失败: {e}")
            return None


class BaostockDownloader(IDataDownloader):
    """Baostock 兜底"""

    def available(self) -> bool:
        try:
            from .baostock_fetcher import available as _avail
            return _avail()
        except ImportError:
            return False

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        try:
            from .baostock_fetcher import get_daily_kline
            if period != "daily":
                return None
            return get_daily_kline(symbol, start, end)
        except Exception as e:
            logger.debug(f"[BaostockDownloader] {symbol} 失败: {e}")
            return None


# ══════════════════════════════════════════════
# 下载编排器 (类 Lean.CompositeDataProvider)
# ══════════════════════════════════════════════

class DataProvider:
    """
    数据源编排器。多源自动兜底 with freshness check + concurrent protection.

    链路：
      日线:  cache → StockApi(Tencent) → Akshare → Baostock
      分钟线: cache → StockApiMinute(Tencent) → Mootdx(TCP) → Akshare
    """

    def __init__(self):
        # 注册所有数据源
        self._daily_sources = [
            StockApiDownloader(),
            AkshareDownloader(),
            BaostockDownloader(),
        ]
        self._minute_sources = [
            StockApiMinuteDownloader(),
            MootdxDownloader(),
        ]

    # ── 新鲜度检查 (类 Lean.NeedToDownload) ──

    def need_to_download(self, symbol: str, period: str = "daily") -> bool:
        """
        检查是否需要下载该股票该周期的数据（基于 kline_cache 最新时间戳）。
        分钟线(5m/15m等): 检查当天有无数据
        日线: 检查最近交易日有无数据
        """
        try:
            from .cache import _get_conn
            conn = _get_conn()
            try:
                today = date.today().strftime("%Y-%m-%d")
                if period in ("1m", "5m", "15m", "30m", "60m"):
                    # 分钟线：当天有没有数据
                    row = conn.execute(
                        "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=? AND trade_date LIKE ?",
                        (symbol, period, f"{today}%")
                    ).fetchone()
                    return row is None or row[0] == 0
                else:
                    # 日线：看最新数据距今几天
                    row = conn.execute(
                        "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period=?",
                        (symbol, period)
                    ).fetchone()
                    if row and row[0]:
                        last = row[0][:10]
                        days_ago = (date.today() - datetime.strptime(last, "%Y-%m-%d").date()).days
                        return days_ago > 1  # 超过1天没数据就重下
                    return True  # 从未下载过
            finally:
                conn.close()
        except Exception:
            return True  # 出错时默认需要下载

    # ── 并发保护下载 (类 Lean.DownloadOnce) ──

    def download_once(self, key: str, download_fn: Callable, timeout: float = 60) -> any:
        """
        保证同一 key 只被下载一次（并发安全）。
        类 Lean 的 _singleDownloadSynchronizer.Execute()
        """
        global _download_locks

        # 获取/创建 key 级锁
        with _download_lock_global:
            if key not in _download_locks:
                _download_locks[key] = threading.Lock()

        lock = _download_locks[key]
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            logger.warning(f"[DownloadOnce] {key} 获取锁超时（{timeout}s），跳过")
            return None

        try:
            # 再次检查是否需要（防止竞争）
            return download_fn()
        except Exception as e:
            logger.error(f"[DownloadOnce] {key} 下载失败: {e}")
            return None
        finally:
            lock.release()

    # ── 数据获取主入口 ──

    def get_kline(self, symbol: str, period: str = "daily",
                  start: str = None, end: str = None,
                  force_download: bool = False) -> Optional[pd.DataFrame]:
        """
        获取K线数据，多源自动兜底。

        流程:
          1. 检查缓存是否新鲜 (NeedToDownload)
          2. 缓存新鲜 → 直接返回
          3. 缓存不新鲜 → 串行遍历数据源依次重试
          4. 写入缓存 → 返回

        Args:
            symbol: 股票代码，支持 SH.600519 或 600519
            period: 周期 daily/5m/15m/30m/60m
            start/end: 日期范围
            force_download: 强制重下（忽略缓存）
        """
        from .cache import save_kline as _save_cache
        from datetime import datetime

        # 标准化 symbol（去前缀给 fetcher 用）
        clean_sym = symbol.split(".")[-1] if "." in symbol else symbol

        if not end:
            end = date.today().strftime("%Y-%m-%d")
        if not start:
            start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")

        # 1. 缓存命中且新鲜
        if not force_download:
            cache_key = f"{symbol}_{period}"
            if not self.need_to_download(symbol, period):
                # 不按 source 过滤（兼容任意数据源）
                from .cache import _get_conn
                conn = _get_conn()
                try:
                    sql = "SELECT * FROM kline_cache WHERE symbol=? AND period=?"
                    params = [symbol, period]
                    if start:
                        sql += " AND DATE(trade_date)>=?"
                        params.append(start)
                    if end:
                        sql += " AND DATE(trade_date)<=?"
                        params.append(end)
                    sql += " ORDER BY trade_date ASC"
                    cached = pd.read_sql(sql, conn, params=params)
                finally:
                    conn.close()

                if cached is not None and not cached.empty:
                    logger.debug(f"[DataProvider] {cache_key} 缓存命中 ({len(cached)} 条)")
                    return cached

        # 2. 选择数据源列表
        sources = self._daily_sources if period == "daily" else self._minute_sources

        # 3. 串行遍历（并发保护）
        dl_key = f"{clean_sym}_{period}"
        result = [None]

        def _try_all_sources():
            for src in sources:
                if not src.available():
                    continue
                logger.debug(f"[DataProvider] {dl_key} → {src.name()}...")
                df = src.get_kline(clean_sym, period=period, start=start, end=end)
                if df is not None and not df.empty:
                    result[0] = df
                    logger.info(f"[DataProvider] {dl_key} 来自 {src.name()}: {len(df)} 条")
                    return
            logger.warning(f"[DataProvider] {dl_key} 所有数据源均失败")

        self.download_once(dl_key, _try_all_sources)

        df = result[0]
        if df is not None and not df.empty:
            # 4. 写入缓存
            try:
                _save_cache(symbol if "." in symbol else clean_sym, f"provider_{period}", df, period=period)
            except Exception as e:
                logger.debug(f"[DataProvider] 缓存写入失败: {e}")

        return df


# ══════════════════════════════════════════════
# 全局实例
# ══════════════════════════════════════════════

_default_provider = None


def get_provider() -> DataProvider:
    """获取全局 DataProvider 实例（单例）"""
    global _default_provider
    if _default_provider is None:
        _default_provider = DataProvider()
    return _default_provider


def need_to_download(symbol: str, period: str = "daily") -> bool:
    """快捷调用"""
    return get_provider().need_to_download(symbol, period)


def download_once(key: str, fn: Callable, timeout: float = 60):
    """快捷调用"""
    return get_provider().download_once(key, fn, timeout)


def get_kline(symbol: str, period: str = "daily",
              start: str = None, end: str = None,
              force_download: bool = False) -> Optional[pd.DataFrame]:
    """快捷调用"""
    return get_provider().get_kline(symbol, period, start, end, force_download)
