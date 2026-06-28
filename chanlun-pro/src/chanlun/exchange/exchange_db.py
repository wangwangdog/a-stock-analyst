import datetime
import os
import re
import sqlite3
from typing import Dict, List, Union

import pandas as pd
import pytz
from tzlocal import get_localzone

from chanlun import fun
from chanlun.base import Market
from chanlun.db import db
from chanlun.exchange.exchange import (
    Exchange,
    Tick,
    convert_currency_kline_frequency,
    convert_futures_kline_frequency,
    convert_stock_kline_frequency,
    convert_us_kline_frequency,
)


class ExchangeDB(Exchange):
    """
    数据库行情
    """

    def __init__(self, market):
        """
        :param market: 市场 a A股市场 hk 香港市场 us 美股市场 currency 数字货币市场  futures 期货市场
        """
        self.market = market
        self.exchange = None
        self.online_ex = None

        # 设置时区
        self.tz = pytz.timezone("Asia/Shanghai")
        if self.market == "us":
            self.tz = pytz.timezone("US/Eastern")
        if self.market in ["currency", "currency_spot"]:
            self.tz = pytz.timezone(str(get_localzone()))

    def default_code(self):
        if self.market == Market.A.value:
            return "SH.000001"
        elif self.market == Market.HK.value:
            return "HK.00700"
        elif self.market == Market.FUTURES.value:
            return "KQ.m@SHFE.rb"
        elif self.market == Market.NY_FUTURES.value:
            return "CO.GC00W"
        elif self.market == Market.US.value:
            return "AAPL"
        elif self.market == Market.CURRENCY.value:
            return "BTC/USDT"
        elif self.market == Market.CURRENCY_SPOT.value:
            return "BTC/USDT"
        return ""

    def support_frequencys(self):
        if self.market == Market.A.value:
            return {
                "y": "Y",
                "m": "M",
                "w": "W",
                "d": "D",
                "120m": "120m",
                "60m": "60m",
                "30m": "30m",
                "15m": "15m",
                "10m": "10m",
                "5m": "5m",
            }
        elif self.market == Market.HK.value:
            return {
                "y": "Y",
                "q": "Q",
                "m": "M",
                "w": "W",
                "d": "D",
                "60m": "60m",
                "30m": "30m",
                "15m": "15m",
                "5m": "5m",
            }
        elif self.market == Market.FUTURES.value:
            return {
                "w": "W",
                "d": "D",
                "120m": "2H",
                "60m": "1H",
                "30m": "30m",
                "15m": "15m",
                "10m": "10m",
                "5m": "5m",
                "1m": "1m",
            }
        elif self.market == Market.NY_FUTURES.value:
            return {
                "w": "W",
                "d": "D",
                "120m": "2H",
                "60m": "1H",
                "30m": "30m",
                "15m": "15m",
                "10m": "10m",
                "5m": "5m",
                "1m": "1m",
            }
        elif self.market == Market.US.value:
            return {
                "w": "Week",
                "d": "Day",
                "60m": "60m",
                "30m": "30m",
                "10m": "10m",
                "15m": "15m",
                "5m": "5m",
            }
        elif self.market == Market.CURRENCY.value:
            return {
                "w": "Week",
                "d": "Day",
                "4h": "4H",
                "60m": "1H",
                "30m": "30m",
                "15m": "15m",
                "10m": "5m",
                "5m": "5m",
                "3m": "3m",
                "2m": "2m",
                "1m": "1m",
            }
        elif self.market == Market.CURRENCY_SPOT.value:
            return {
                "w": "Week",
                "d": "Day",
                "4h": "4H",
                "60m": "1H",
                "30m": "30m",
                "15m": "15m",
                "10m": "5m",
                "5m": "5m",
                "3m": "3m",
                "2m": "2m",
                "1m": "1m",
            }
        return {"d": "D", "30m": "30m"}

    def query_last_datetime(self, code, frequency) -> Union[None, str]:
        """
        查询交易对儿最后更新时间
        :param frequency:
        :param code:
        :return:
        """
        return db.klines_last_datetime(self.market, code, frequency)

    def insert_klines(self, code, frequency, klines):
        """
        批量添加交易对儿Kline数据
        :param code:
        :param frequency
        :param klines:
        :return:
        """
        db.klines_insert(self.market, code, frequency, klines)
        return True

    def del_klines(self, code, frequency, _datetime: datetime.datetime):
        """
        删除一条记录
        """
        db.klines_delete(self.market, code, frequency, _datetime)
        return

    def del_klines_by_code(self, code):
        db.klines_delete(self.market, code)
        return

    def del_klines_by_code_freq(self, code, freq):
        db.klines_delete(self.market, code, frequency=freq)
        return

    def klines(
        self,
        code: str,
        frequency: str,
        start_date: str = None,
        end_date: str = None,
        args=None,
    ) -> Union[pd.DataFrame, None]:
        if args is None:
            args = {}

        limit = 10000
        if "limit" in args.keys():
            limit = args["limit"]
        order = "desc"
        if "order" in args.keys():
            order = args["order"]

        if start_date is not None and end_date is not None and "limit" not in args:
            limit = None
        if start_date is not None:
            start_date = fun.str_to_datetime(start_date)
        if end_date is not None:
            end_date = fun.str_to_datetime(end_date)

        # 从 kline_cache 表读取数据（统一数据源）
        kline_pd = []
        if self.market == Market.A.value:
            import sqlite3, os, re
            _db_path = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
            # 保留完整前缀代码（SH.000001 vs SZ.000001 不再冲突）
            _full_code = code
            _pure_code = re.sub(r'^[A-Z]+\.', '', code)
            _period_map = {"d": "daily", "w": "weekly", "m": "monthly", "y": "yearly",
                           "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m"}
            _p = _period_map.get(frequency, frequency)
            # 先用完整前缀代码查，若无数据则 fallback 到裸码（兼容旧数据）
            # 但全码在其他周期有数据说明是已知品种，跳过 fallback 避免跨品种（如 SH.000001→000001平安银行）
            _full_has_any = None  # 缓存检查结果
            for _try_code in (_full_code, _pure_code):
                # fallback 到裸码前，检查全码是否存在其他周期数据
                if _try_code == _pure_code and _full_code != _pure_code:
                    if _full_has_any is None:
                        try:
                            _ck_conn = sqlite3.connect(_db_path)
                            _full_has_any = _ck_conn.execute(
                                "SELECT 1 FROM kline_cache WHERE symbol=? LIMIT 1",
                                (_full_code,)
                            ).fetchone() is not None
                            _ck_conn.close()
                        except:
                            _full_has_any = False
                    if _full_has_any:
                        break  # 全码已知但缺本次周期数据，跳过裸码 fallback
                try:
                    _conn = sqlite3.connect(_db_path)
                    _sql = ("SELECT trade_date, open, high, low, close, volume "
                            "FROM kline_cache WHERE symbol=? AND period=?")
                    # 日线统一用 tencent_fq（volume 是手数，×100 转股数）
                    if _p == 'daily':
                        _sql += " AND source='tencent_fq'"
                    _params = [_try_code, _p]
                    if start_date:
                        _sql += " AND DATE(trade_date)>=?"
                        _params.append(start_date.strftime("%Y-%m-%d"))
                    if end_date:
                        _sql += " AND DATE(trade_date)<=?"
                        _params.append(end_date.strftime("%Y-%m-%d"))
                    _sql += " ORDER BY trade_date ASC"
                    _df = pd.read_sql(_sql, _conn, params=_params)
                    _conn.close()
                    if not _df.empty:
                        for _, _r in _df.iterrows():
                            _vol = float(_r["volume"])
                            # 日线 tencent_fq 的 volume 是手数，×100 转股
                            if _p == 'daily':
                                _vol *= 100
                            kline_pd.append({
                                "code": code,
                                "date": _r["trade_date"],
                                "open": float(_r["open"]),
                                "high": float(_r["high"]),
                                "low": float(_r["low"]),
                                "close": float(_r["close"]),
                                "volume": _vol,
                            })
                        if limit and len(kline_pd) > limit:
                            kline_pd = kline_pd[-limit:]
                        break  # 找到数据就不再 fallback
                except Exception as _ex:
                    pass

        if len(kline_pd) == 0:
            kline_pd = pd.DataFrame(
                [], columns=["date", "code", "high", "low", "open", "close", "volume"]
            )
            return kline_pd

        kline_pd = pd.DataFrame(kline_pd)
        kline_pd["code"] = code
        # 日期列统一处理
        try:
            if not hasattr(kline_pd["date"].dtype, 'tz') or kline_pd["date"].dtype == object:
                kline_pd["date"] = pd.to_datetime(
                    kline_pd["date"].astype(str).str[:19], format='mixed'
                )
        except Exception:
            kline_pd["date"] = pd.to_datetime(kline_pd["date"].astype(str).str[:19], format='mixed')
        kline_pd["date"] = kline_pd["date"].dt.tz_localize(
            self.tz, ambiguous=True
        )
        kline_pd["date"] = kline_pd["date"].apply(self.__convert_date)
        kline_pd.sort_values(by="date", inplace=True)
        kline_pd = kline_pd.reset_index(drop=True)

        return kline_pd

    def __convert_date(self, dt: datetime.datetime):
        """
        统一各个市场的时间格式
        TODO 需要根据自己数据源的数据格式进行调整
        TODO 将日及以上周期（大多数这类的时间都是 0点0分），修改为交易日结束或开始时间（根据日期是前对其还是后对其来决定是开盘时间还是收盘时间）
        """
        if self.market == Market.A.value:
            if dt.hour == 0 and dt.minute == 0:
                return dt.replace(hour=15, minute=0)
        if self.market == Market.HK.value:
            if dt.hour == 0 and dt.minute == 0:
                return dt.replace(hour=16, minute=0)
        if self.market == Market.FUTURES.value:
            if dt.hour == 0 and dt.minute == 0:
                return dt.replace(hour=9, minute=0)
        if self.market == Market.US.value:
            if dt.hour == 0 and dt.minute == 0:
                return dt.replace(hour=9, minute=30)
        return dt

    def convert_kline_frequency(self, klines: pd.DataFrame, to_f: str) -> pd.DataFrame:
        """
        转换K线周期
        """
        if (
            self.market == Market.CURRENCY.value
            or self.market == Market.CURRENCY_SPOT.value
        ):
            return convert_currency_kline_frequency(klines, to_f)
        elif self.market == Market.FUTURES.value:
            return convert_futures_kline_frequency(klines, to_f)
        elif self.market == Market.US.value:
            return convert_us_kline_frequency(klines, to_f)
        else:
            return convert_stock_kline_frequency(klines, to_f)

    def all_stocks(self):
        try:
            _db_path = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
            _conn = sqlite3.connect(_db_path)
            rows = _conn.execute(
                "SELECT symbol, name FROM all_stock_info ORDER BY symbol"
            ).fetchall()
            _conn.close()
            return [
                {"code": r[0], "name": r[1], "exchange": "SZ" if r[0].startswith(("0", "3")) else "SH"}
                for r in rows
            ]
        except Exception:
            return []

    def now_trading(self):
        pass

    def ticks(self, codes: List[str]) -> Dict[str, Tick]:
        ticks = {}
        for _code in codes:
            klines = self.klines(_code, "d", args={"limit": 2})
            if len(klines) == 0:
                # 日线无数据时，用 5m 兜底（指数 SH.000001 只有分钟线，没有 daily）
                klines = self.klines(_code, "5m", args={"limit": 2})
            if len(klines) == 0:
                continue
            _last = klines.iloc[-1]
            _prev = klines.iloc[-2] if len(klines) >= 2 else _last
            _rate = round((_last["close"] - _prev["close"]) / _prev["close"] * 100, 2) if _prev["close"] != 0 else 0.0
            ticks[_code] = Tick(
                _code,
                _last["close"],
                _last["close"],
                _last["close"],
                _last["high"],
                _last["low"],
                _last["open"],
                _last["volume"],
                _rate,
            )
        return ticks

    def stock_info(self, code: str) -> Dict:
        # 常见指数名称映射（带前缀的完整代码）
        _index_names = {
            "SH.000001": "上证指数",
            "SH.000688": "科创50",
            "SZ.399001": "深证成指",
            "SZ.399006": "创业板指",
            "SZ.399005": "中小板指",
            "SH.000016": "上证50",
            "SH.000300": "沪深300",
            "SH.000905": "中证500",
            "SH.000852": "中证1000",
        }
        if code in _index_names:
            return {"code": code, "name": _index_names[code]}

        # 从 all_stock_info 表查个股名称
        try:
            _pure_code = re.sub(r'^[A-Z]+\\.', '', code)
            _db_path = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
            _conn = sqlite3.connect(_db_path)
            _row = _conn.execute(
                "SELECT name FROM all_stock_info WHERE symbol=? LIMIT 1",
                (_pure_code,)
            ).fetchone()
            _conn.close()
            if _row:
                _name = _row[0].strip()
                return {"code": code, "name": _name}
        except Exception:
            pass

        return {
            "code": code,
            "name": code,
        }

    def stock_owner_plate(self, code: str):
        pass

    def plate_stocks(self, code: str):
        pass

    def balance(self):
        pass

    def positions(self, code: str = ""):
        pass

    def order(self, code: str, o_type: str, amount: float, args=None):
        pass


if __name__ == "__main__":
    ex = ExchangeDB(Market.CURRENCY_SPOT.value)
    # ticks = ex.ticks(['SHSE.000001'])
    # print(ticks)

    # ex.del_klines_by_code_freq("BTC/USDT", "4h")

    klines = ex.klines(
        "BTC/USDT",
        "4h",
        # start_date="2023-12-01 00:00:00",
        args={"limit": 10000},
    )
    print(len(klines))
    print(klines.head(5))
    print(klines.tail(5))
