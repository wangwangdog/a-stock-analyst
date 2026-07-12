"""产业链全景快照 - 盘后自动生成"""
import sys
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/a-stock-analyst')
from backend.data_fetcher.chain_engine import generate_market_snapshot

snap = generate_market_snapshot()

print(f'=== {snap["timestamp"]} 产业链全景快照 ===')
print()
print('--- 热门概念 TOP10 ---')
for c in snap['hot_concepts'][:10]:
    print(f'  {c["concept"]}: {c["zt_count"]}只涨停(连板{c["total_limit_days"]}天)')
print()
print('--- 热门行业 TOP5 ---')
for i in snap['industry_heat'][:5]:
    print(f'  {i["industry"]}: {i["zt_count"]}只涨停')
print()
print('--- 龙虎榜 TOP5 ---')
for d in snap['top_dragon_tiger'][:5]:
    print(f'  {d["name"]}: 净买{d["net_buy"]/1e4:.0f}万')
print()
print('--- 产业链预警 ---')
for a in snap['chain_alerts']:
    print(f'  [{a["severity"]}] {a["supplier"]} 被{a["dependent_count"]}家依赖')
