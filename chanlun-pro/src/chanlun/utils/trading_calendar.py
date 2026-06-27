"""
交易日历模块

使用 merged DB 的 trade_calendar 表判断交易日（第一优先级），
缓存 JSON 为第二优先级，AKShare 网络为第三优先级。

所有外部调用都有 timeout 保护，超时时优雅降级到 heuristic 规则。
"""

import json
import logging
import signal
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# ── 缓存目录 ──
_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
_CACHE_FILE = _CACHE_DIR / "trading_calendar.json"

# ── merged DB 路径 ──
_MERGED_DB_DIR = Path.home() / ".chanlun_pro" / "db"
_MERGED_DB = _MERGED_DB_DIR / "chanlun_klines.sqlite"


def _timeout_proxy(timeout_sec: int = 10):
    """装饰器：给外部调用加 timeout 保护"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            import threading

            result = [None]
            exception = [None]
            done = threading.Event()

            def worker():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
                finally:
                    done.set()

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            if done.wait(timeout=timeout_sec):
                if exception[0]:
                    raise exception[0]
                return result[0]
            else:
                raise TimeoutError(f"调用超时 ({timeout_sec}s)")
        return wrapper
    return decorator


class TradingCalendar:
    """A 股交易日历

    数据来源优先级：
      1. merged DB 的 trade_calendar 表（calendar_date TEXT, is_trading_day INTEGER）
      2. 本地 JSON 缓存
      3. AKShare 网络获取
      4. Heuristic（周末判断）

    所有外部 API 调用均带 timeout 保护。
    """

    def __init__(self, cache_days: int = 365, auto_load: bool = True):
        self.cache_days = cache_days
        self._trading_dates: Set[str] = set()
        self._sorted_dates: List[str] = []
        self._loaded: bool = False
        self._source: str = ""

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if auto_load:
            self.load()

    # ────────────────────── 加载 ──────────────────────

    def load(self) -> bool:
        """尝试从数据源加载交易日历（优先级：DB > JSON > AKShare > heuristic）"""
        # 第一优先：merged DB
        if self._load_from_db():
            return True
        # 第二优先：JSON 缓存
        if self._load_from_json():
            return True
        # 第三优先：AKShare（带 timeout）
        if self._fetch_from_akshare():
            return True
        # 备选：heuristic（跳过周末）
        logger.warning("所有数据源均不可用，使用 heuristic 规则")
        self._generate_heuristic()
        return True

    def _load_from_db(self) -> bool:
        """从 merged DB 的 trade_calendar 表加载"""
        if not _MERGED_DB.exists():
            logger.warning(f"merged DB 不存在: {_MERGED_DB}")
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(_MERGED_DB))
            # 检查表是否存在
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trade_calendar'"
            )
            if not cur.fetchone():
                conn.close()
                logger.warning("merged DB 中无 trade_calendar 表")
                return False

            cur = conn.execute("SELECT calendar_date, is_trading_day FROM trade_calendar")
            rows = cur.fetchall()
            conn.close()

            if not rows:
                return False

            self._trading_dates = {r[0] for r in rows if r[1] == 1}
            self._sorted_dates = sorted(self._trading_dates)
            self._loaded = True
            self._source = f"merged_db ({len(self._trading_dates)} days)"
            logger.info(f"交易日历已从 merged DB 加载: {len(self._trading_dates)} 个交易日")
            return True
        except Exception as e:
            logger.warning(f"从 merged DB 加载交易日历失败: {e}")
            return False

    def _load_from_json(self) -> bool:
        """从本地 JSON 缓存加载"""
        if not _CACHE_FILE.exists():
            return False
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            self._trading_dates = set(data.get("trading_dates", []))
            self._sorted_dates = sorted(self._trading_dates)
            self._loaded = True
            self._source = f"json_cache ({len(self._trading_dates)} days)"
            logger.info(f"交易日历已从缓存加载: {len(self._trading_dates)} 个交易日")
            return True
        except Exception as e:
            logger.warning(f"交易日历缓存加载失败: {e}")
            return False

    @_timeout_proxy(10)
    def _fetch_from_akshare(self) -> bool:
        """从 AKShare 获取（带 timeout 10s）"""
        try:
            import akshare as ak
        except ImportError:
            logger.error("需要安装 akshare: pip install akshare")
            return False

        try:
            df = ak.tool_trade_date_hist_sina()
            today = date.today()
            start_dt = today - timedelta(days=365 * 3)
            end_dt = today + timedelta(days=365 * 3)

            self._trading_dates.clear()
            for _, row in df.iterrows():
                try:
                    dt = datetime.strptime(str(row["trade_date"]), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
                if dt < start_dt or dt > end_dt:
                    continue
                if row.get("is_open", 1) == 1 or row.get("close", 0) > 0:
                    self._trading_dates.add(dt.isoformat())

            self._sorted_dates = sorted(self._trading_dates)
            self._loaded = True
            self._source = f"akshare ({len(self._trading_dates)} days)"
            self._save_json()
            logger.info(f"交易日历获取完成: {len(self._trading_dates)} 交易日")
            return True
        except TimeoutError:
            logger.warning("AKShare 获取交易日历超时")
            return False
        except Exception as e:
            logger.warning(f"AKShare 获取交易日历失败: {e}")
            return False

    def _generate_heuristic(self):
        """生成 heuristic 交易日历（仅排除周末）"""
        today = date.today()
        start_dt = today - timedelta(days=365 * 3)
        end_dt = today + timedelta(days=365 * 3)
        self._trading_dates = set()
        cur = start_dt
        while cur <= end_dt:
            if cur.weekday() < 5:  # 周一到周五
                self._trading_dates.add(cur.isoformat())
            cur += timedelta(days=1)
        self._sorted_dates = sorted(self._trading_dates)
        self._loaded = True
        self._source = f"heuristic ({len(self._trading_dates)} days)"
        logger.info(f"交易日历 heuristic 生成: {len(self._trading_dates)} 个交易日")

    def _save_json(self):
        """保存到 JSON 缓存"""
        if not self._trading_dates:
            return
        data = {
            "trading_dates": sorted(self._trading_dates),
            "updated_at": date.today().isoformat(),
        }
        _CACHE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ────────────────────── 查询方法 ──────────────────────

    def is_trading_day(self, day: Optional[str] = None) -> bool:
        day_str = day or date.today().isoformat()
        if not self._loaded:
            return True  # fallback
        return day_str in self._trading_dates

    def get_latest_trading_day(self, day: Optional[str] = None) -> str:
        day_str = day or date.today().isoformat()
        if self._trading_dates:
            target = day_str
            while target not in self._trading_dates:
                dt = datetime.strptime(target, "%Y-%m-%d").date() - timedelta(days=1)
                target = dt.isoformat()
                if dt < date(1990, 12, 19):
                    return day_str
            return target
        # fallback
        dt = datetime.strptime(day_str, "%Y-%m-%d").date()
        while dt.weekday() >= 5:
            dt -= timedelta(days=1)
        return dt.isoformat()

    def get_next_trading_day(self, day: Optional[str] = None) -> str:
        day_str = day or date.today().isoformat()
        if self._trading_dates:
            target = day_str
            while target not in self._trading_dates:
                dt = datetime.strptime(target, "%Y-%m-%d").date() + timedelta(days=1)
                target = dt.isoformat()
                if dt > date(2100, 1, 1):
                    return day_str
            return target
        dt = datetime.strptime(day_str, "%Y-%m-%d").date()
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
        return dt.isoformat()

    def get_trading_days_between(self, start: str, end: str) -> List[str]:
        if self._trading_dates:
            return [d for d in self._sorted_dates if start <= d <= end]
        result = []
        dt_start = datetime.strptime(start, "%Y-%m-%d").date()
        dt_end = datetime.strptime(end, "%Y-%m-%d").date()
        current = dt_start
        while current <= dt_end:
            if current.weekday() < 5:
                result.append(current.isoformat())
            current += timedelta(days=1)
        return result

    def is_market_open(self) -> bool:
        now = datetime.now()
        if not self.is_trading_day():
            return False
        hour, minute = now.hour, now.minute
        if (hour == 9 and minute >= 30) or hour == 10 or (hour == 11 and minute <= 30):
            return True
        if hour == 13 or hour == 14 or (hour == 15 and minute == 0):
            return True
        return False

    def count_trading_days_until(self, end: str, start: Optional[str] = None) -> int:
        start = start or date.today().isoformat()
        return len(self.get_trading_days_between(start, end))

    @property
    def all_trading_dates(self) -> List[str]:
        return self._sorted_dates

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def source(self) -> str:
        return self._source


# ── 模块级单例 ──
_default_calendar: Optional[TradingCalendar] = None


def get_calendar() -> TradingCalendar:
    global _default_calendar
    if _default_calendar is None:
        _default_calendar = TradingCalendar()
    return _default_calendar


def is_trading_day(day: Optional[str] = None) -> bool:
    return get_calendar().is_trading_day(day)


def latest_trading_day(day: Optional[str] = None) -> str:
    return get_calendar().get_latest_trading_day(day)


def next_trading_day(day: Optional[str] = None) -> str:
    return get_calendar().get_next_trading_day(day)
