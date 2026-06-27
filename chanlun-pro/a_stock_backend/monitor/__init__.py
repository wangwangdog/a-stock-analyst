"""
盘口异动监控模块

基于东方财富盘口异动 API（akshare.stock_changes_em），
提供10类盘口异动的批量/单类查询接口。

异动类型代码映射:
    8193 - 大笔买入    8194 - 大笔卖出
    8201 - 火箭发射    8203 - 高台跳水
    8202 - 快速反弹    8204 - 加速下跌
    4    - 封涨停板    16   - 打开涨停板
    8    - 封跌停板    32   - 打开跌停板
    64   - 有大买盘    128  - 有大卖盘
    8207 - 竞价上涨    8208 - 竞价下跌
    8209 - 高开5日线   8210 - 低开5日线
    8211 - 向上缺口    8212 - 向下缺口
    8213 - 60日新高    8214 - 60日新低
    8215 - 60日大幅上涨 8216 - 60日大幅下跌
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger('akshare_monitor')


# ── 异动类型分类（10大类） ──

ABNORMAL_TYPES = {
    # 1. 大单异动
    "large_buy":  "大笔买入",
    "large_sell": "大笔卖出",
    # 2. 走势异动
    "rocket":     "火箭发射",
    "cliff_dive": "高台跳水",
    # 3. 涨跌异动
    "rapid_bounce":  "快速反弹",
    "accelerate_drop": "加速下跌",
    # 4. 涨停相关
    "limit_up":          "封涨停板",
    "limit_up_break":    "打开涨停板",
    # 5. 跌停相关
    "limit_down":        "封跌停板",
    "limit_down_break":  "打开跌停板",
    # 6. 盘口压力
    "big_buy_pressure":  "有大买盘",
    "big_sell_pressure": "有大卖盘",
    # 7. 竞价异动
    "auction_up":   "竞价上涨",
    "auction_down": "竞价下跌",
    # 8. 均线缺口
    "gap_above_ma5": "高开5日线",
    "gap_below_ma5": "低开5日线",
    # 9. 缺口异动
    "gap_up":   "向上缺口",
    "gap_down": "向下缺口",
    # 10. 新高新低
    "high_60d":       "60日新高",
    "low_60d":        "60日新低",
    "big_up_60d":     "60日大幅上涨",
    "big_down_60d":   "60日大幅下跌",
}

# 异动中文名 → 英文key 反向映射
REVERSE_TYPE_MAP = {v: k for k, v in ABNORMAL_TYPES.items()}

# 分类分组
CATEGORIES = {
    "大单异动":   ["large_buy", "large_sell"],
    "走势异动":   ["rocket", "cliff_dive"],
    "涨跌异动":   ["rapid_bounce", "accelerate_drop"],
    "涨停相关":   ["limit_up", "limit_up_break"],
    "跌停相关":   ["limit_down", "limit_down_break"],
    "盘口压力":   ["big_buy_pressure", "big_sell_pressure"],
    "竞价异动":   ["auction_up", "auction_down"],
    "均线缺口":   ["gap_above_ma5", "gap_below_ma5"],
    "缺口异动":   ["gap_up", "gap_down"],
    "新高新低":   ["high_60d", "low_60d", "big_up_60d", "big_down_60d"],
}


class AKShareMonitor:
    """盘口异动监控器

    封装东方财富盘口异动数据接口，提供单类查询与全量扫描能力。

    Usage:
        >>> mon = AKShareMonitor()
        >>> mon.get_changes("大笔买入")
        >>> mon.scan_all()
        >>> mon.get_stock_changes("000001")
    """

    def __init__(self):
        self._last_query_time: Optional[datetime] = None

    @staticmethod
    def get_changes(change_type: str, top_n: int = 100) -> List[Dict]:
        """获取某类盘口异动的实时数据

        Args:
            change_type: 异动中文名，如 "大笔买入", "封涨停板"
            top_n: 返回前 N 条

        Returns:
            [{"time": "09:35:00", "code": "000001", "name": "平安银行", "board": "深股通", "change_type": "大笔买入"}, ...]
        """
        import akshare as ak

        try:
            df = ak.stock_changes_em(symbol=change_type)
        except Exception as e:
            logger.error(f"获取 {change_type} 异动失败: {e}")
            return []

        if df is None or df.empty:
            return []

        result = df.to_dict(orient="records")
        for r in result:
            r["time"] = str(r.get("时间", ""))
            r["code"] = str(r.get("代码", ""))
            r["name"] = str(r.get("名称", ""))
            r["board"] = str(r.get("板块", ""))
            r["change_type"] = change_type
            # 清理辅助字段
            r.pop("时间", None)
            r.pop("代码", None)
            r.pop("名称", None)
            r.pop("板块", None)

        return result[:top_n]

    def scan_all(self, top_n_per_type: int = 50) -> Dict[str, List[Dict]]:
        """扫描所有异动类型

        Args:
            top_n_per_type: 每类返回前 N 条

        Returns:
            {"大单异动": [...], "涨停相关": [...], ...}
        """
        results = {}
        for category, type_keys in CATEGORIES.items():
            category_results = []
            for key in type_keys:
                cn_name = ABNORMAL_TYPES.get(key)
                if not cn_name:
                    continue
                items = self.get_changes(cn_name, top_n=top_n_per_type)
                category_results.extend(items)
            results[category] = category_results

        self._last_query_time = datetime.now()
        return results

    def get_stock_changes(self, symbol: str, top_n: int = 100) -> List[Dict]:
        """查询某个股票的所有异动

        Args:
            symbol: 股票代码（纯数字或带后缀）
            top_n: 返回前 N 条每条异动类型最多返回的条数

        Returns:
            sorted by time
        """
        all_records = []
        for cn_name in REVERSE_TYPE_MAP:
            try:
                items = self.get_changes(cn_name, top_n=100)
            except Exception:
                continue
            for item in items:
                code = item.get("code", "")
                # 支持多种格式匹配
                if code == symbol or code.lstrip("0") == symbol.lstrip("0") or code.endswith(symbol):
                    all_records.append(item)

        # 按时间排序
        all_records.sort(key=lambda x: x.get("time", ""))
        return all_records[:top_n]

    @staticmethod
    def get_summary() -> Dict:
        """获取盘口异动概览（全市场各类型异动次数统计）

        Returns:
            {"大笔买入": 15, "大笔卖出": 8, ...}
        """
        import akshare as ak
        import pandas as pd

        summary = {}
        for cn_name in REVERSE_TYPE_MAP:
            try:
                df = ak.stock_changes_em(symbol=cn_name)
                summary[cn_name] = len(df) if df is not None else 0
            except Exception as e:
                logger.debug(f"获取 {cn_name} 统计失败: {e}")
                summary[cn_name] = 0

        return summary

    @property
    def last_query_time(self) -> Optional[datetime]:
        return self._last_query_time


# 模块级单例
_default_monitor: Optional[AKShareMonitor] = None


def get_monitor() -> AKShareMonitor:
    """获取全局监控器单例"""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = AKShareMonitor()
    return _default_monitor


def get_changes(change_type: str, top_n: int = 100) -> List[Dict]:
    """快捷查询某类异动"""
    return get_monitor().get_changes(change_type, top_n)


def scan_all(top_n_per_type: int = 50) -> Dict[str, List[Dict]]:
    """快捷全量扫描"""
    return get_monitor().scan_all(top_n_per_type=top_n_per_type)


def get_stock_changes(symbol: str, top_n: int = 100) -> List[Dict]:
    """快捷查询个股异动"""
    return get_monitor().get_stock_changes(symbol, top_n)


def get_summary() -> Dict:
    """快捷获取异动概览"""
    return get_monitor().get_summary()
