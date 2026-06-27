"""Data source manager stub."""

class USDataSource:
    MONGODB = "mongodb"
    YFINANCE = "yfinance"
    ALPHA_VANTAGE = "alpha_vantage"
    FINNHUB = "finnhub"

class USDataSourceManager:
    def __init__(self):
        pass

def get_china_stock_info_unified(ticker):
    from .interface import get_china_stock_info_unified
    return get_china_stock_info_unified(ticker)
