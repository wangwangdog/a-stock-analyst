"""AKShare provider stub."""

class AKShareProvider:
    """AKShare data provider."""
    def __init__(self):
        pass
    
    def get_stock_data(self, *args, **kwargs):
        return None

def get_akshare_provider():
    return AKShareProvider()
