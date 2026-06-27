#!/usr/bin/env python3
"""Test the stock supplement route handler"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'a_stock_backend'))

from routes.stock_supplement import fetch_tencent_quote

result = fetch_tencent_quote(['SZ.000001'])
print(f'Result: {result}')
