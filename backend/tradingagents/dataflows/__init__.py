import sys as _sys

# 导入基础模块
# Finnhub 工具（支持新旧路径）
try:
    from .providers.us import get_data_in_range
except ImportError:
    try:
        from .finnhub_utils import get_data_in_range
    except ImportError:
        get_data_in_range = None

# 导入新闻模块（新路径）
try:
    from .news import getNewsData, fetch_top_from_category
except ImportError:
    # 向后兼容：尝试从旧路径导入
    try:
        from .news.google_news import getNewsData
    except ImportError:
        getNewsData = None
    try:
        from .news.reddit import fetch_top_from_category
    except ImportError:
        fetch_top_from_category = None

# 导入日志模块
from tradingagents.utils.logging_manager import get_logger
logger = get_logger('agents')

# 尝试导入yfinance相关模块（支持新旧路径）
try:
    from .providers.us import YFinanceUtils, YFINANCE_AVAILABLE
except ImportError:
    try:
        from .yfin_utils import YFinanceUtils
        YFINANCE_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"⚠️ yfinance模块不可用: {e}")
        YFinanceUtils = None
        YFINANCE_AVAILABLE = False

# 导入技术指标模块（新路径）
try:
    from .technical import StockstatsUtils, STOCKSTATS_AVAILABLE
except ImportError as e:
    # 向后兼容：尝试从旧路径导入
    try:
        from .technical.stockstats import StockstatsUtils
        STOCKSTATS_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"⚠️ stockstats模块不可用: {e}")
        StockstatsUtils = None
        STOCKSTATS_AVAILABLE = False

# Stub for yfinance utils (to suppress warning)
_yfin_stub = type(_sys)('yfin_utils')
_sys.modules['tradingagents.dataflows.yfin_utils'] = _yfin_stub

# Re-export from interface module
from .interface import (
    set_config,
    get_china_stock_data_unified,
    get_china_stock_info_unified,
    get_china_market_overview,
    get_chinese_social_sentiment,
    get_google_news,
    get_realtime_stock_news,
    get_china_fundamentals,
    get_stockstats_indicators_report,
)

# Stubs for functions used by agents but not critical to A-share analysis
def get_finnhub_news(*args, **kwargs):
    return None
def get_finnhub_company_insider_sentiment(*args, **kwargs):
    return None
def get_finnhub_company_insider_transactions(*args, **kwargs):
    return None
def get_reddit_global_news(*args, **kwargs):
    return None
def get_reddit_company_news(*args, **kwargs):
    return None
def get_simfin_balance_sheet(*args, **kwargs):
    return None
def get_simfin_cashflow(*args, **kwargs):
    return None
def get_simfin_income_statements(*args, **kwargs):
    return None
def get_stock_stats_indicators_window(*args, **kwargs):
    return None
def get_stockstats_indicator(*args, **kwargs):
    return None
def get_YFin_data_window(*args, **kwargs):
    return None
def get_YFin_data(*args, **kwargs):
    return None
def get_china_stock_data_tushare(*args, **kwargs):
    return None
def get_china_stock_fundamentals_tushare(*args, **kwargs):
    return None
def switch_china_data_source(*args, **kwargs):
    pass
def get_current_china_data_source(*args, **kwargs):
    return 'akshare'
def get_hk_stock_data_unified(*args, **kwargs):
    return None
def get_hk_stock_info_unified(*args, **kwargs):
    return None
def get_stock_data_by_market(*args, **kwargs):
    return None
