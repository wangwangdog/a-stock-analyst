"""Cache manager stub."""

class StockDataCache:
    def __init__(self, *args, **kwargs):
        pass
    
    def get(self, *args, **kwargs):
        return None
    
    def set(self, *args, **kwargs):
        pass

def get_cache():
    return StockDataCache()
