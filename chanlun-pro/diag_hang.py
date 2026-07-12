#!/usr/bin/env python3
"""诊断 — 加打印定位死循环"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import time
from chanlun.cl2 import _build_zss_from_bis

class MockFX:
    def __init__(self, val, k=None):
        self.val = val
        self.k = k
        
class MockLine:
    def __init__(self, sv, ev, typ, idx):
        self.start = MockFX(sv)
        self.end = MockFX(ev)
        self.type = typ
        self.index = idx
        self.high = max(sv, ev)
        self.low = min(sv, ev)

bis = [
    MockLine(3000, 3200, "up", 0),
    MockLine(3200, 3100, "down", 1),
    MockLine(3100, 3150, "up", 2),
    MockLine(3150, 3050, "down", 3),
    MockLine(3050, 3300, "up", 4),
]

print("Starting _build_zss_from_bis...", flush=True)
t0 = time.time()
zss = _build_zss_from_bis(bis, config={"zs_extend": 1})
print(f"Done in {time.time()-t0:.2f}s, zss={len(zss)}", flush=True)
