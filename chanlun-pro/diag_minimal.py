#!/usr/bin/env python3
"""极简测试"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import time
t0 = time.time()

from chanlun.cl2 import _build_zss_from_bis
print(f"import: {time.time()-t0:.1f}s", flush=True)

# Create mock BI objects
class MockFX:
    def __init__(self, val, k=None):
        self.val = val
        self.k = k

class MockLine:
    def __init__(self, start_val, end_val, typ, idx, high=None, low=None):
        self.start = MockFX(start_val)
        self.end = MockFX(end_val)
        self.type = typ
        self.index = idx
        self.high = high if high is not None else max(start_val, end_val)
        self.low = low if low is not None else min(start_val, end_val)
        
    def _high(self): return self.high
    def _low(self): return self.low

# Create a list of pens that should form exactly one center
# up, down, up, down, up pattern
bis = [
    MockLine(3000, 3200, "up", 0),    # enter: 3000→3200
    MockLine(3200, 3100, "down", 1),   # mid1: 3200→3100
    MockLine(3100, 3150, "up", 2),     # mid2: 3100→3150
    MockLine(3150, 3050, "down", 3),   # mid3: 3150→3050
    MockLine(3050, 3300, "up", 4),     # exit: 3050→3300, breaks above ZG
    # extension pens
    MockLine(3300, 3200, "down", 5),   # ext1: overlaps
    MockLine(3200, 3400, "up", 6),     # ext2: overlaps
    MockLine(3400, 3500, "down", 7),   # ext3: both above ZG → terminate
]

t1 = time.time()
zss = _build_zss_from_bis(bis, config={"zs_extend": 1})
t2 = time.time()
print(f"build: {t2-t1:.2f}s", flush=True)
print(f"zss: {len(zss)}", flush=True)
for zs in zss:
    print(f"  ZS {zs.type} lines={zs.line_num} indices={[b.index for b in zs.lines]}", flush=True)
