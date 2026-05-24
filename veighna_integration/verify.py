"""
验证 VeighNa 融合第二阶段：
1. 回测引擎 + vnpy_chanlun 适配器跑通
2. 6大策略逐个回测
3. Alpha158 因子计算
"""
import sys
sys.path.insert(0, "/home/dogzi/.openclaw/workspace/veighna")
sys.path.insert(0, "/home/dogzi/.openclaw/workspace/chanlun-pro")
sys.path.insert(0, "/home/dogzi/.openclaw/workspace/a-stock-analyst")

from veighna_integration.backtest_engine import LightweightBacktestEngine
from veighna_integration.sequoia_cta_strategies import STRATEGIES
from veighna_integration.alpha_factors import compute_factors_pipeline

# ═══ 1. 回测验证 ═══
print("=" * 60)
print("1. 回测引擎验证: 000001 + 均线放量策略")
print("=" * 60)

engine = LightweightBacktestEngine(capital=100_000)
_, ma_fn = STRATEGIES["ma_volume"]
result = engine.run("000001", ma_fn, "2025-01-01", "2026-05-16", "均线放量")
print(f"  标的: {result.symbol}")
print(f"  策略: {result.strategy}")
print(f"  初始资金: {result.initial_capital:,.0f}")
print(f"  最终净值: {result.final_nav:.4f}")
print(f"  总收益率: {result.total_return:.2f}%")
print(f"  年化收益: {result.annual_return:.2f}%")
print(f"  夏普比: {result.sharpe_ratio:.2f}")
print(f"  最大回撤: {result.max_drawdown:.2f}%")
print(f"  胜率: {result.win_rate:.1f}%")
print(f"  交易次数: {result.trade_count}")

# ═══ 2. 6大策略批量回测 ═══
print(f"\n{'='*60}")
print("2. 6大策略批量回测")
print("=" * 60)

test_symbols = ["000001", "600519", "300750"]
for sym in test_symbols:
    print(f"\n  📊 {sym}:")
    for key, (name, fn) in STRATEGIES.items():
        try:
            r = engine.run(sym, fn, "2025-01-01", "2026-05-16", name)
            print(f"    {name:10s} | 收益:{r.total_return:7.2f}% | 夏普:{r.sharpe_ratio:5.2f} | 回撤:{r.max_drawdown:6.2f}% | 交易:{r.trade_count}次")
        except Exception as e:
            print(f"    {name:10s} | ❌ {str(e)[:50]}")

# ═══ 3. Alpha158 因子计算 ═══
print(f"\n{'='*60}")
print("3. Alpha158 因子计算: 000001")
print("=" * 60)

df = compute_factors_pipeline(["000001"], days=250)
factor_cols = [c for c in df.columns if c not in ("open","high","low","close","volume","amount")]
print(f"  因子数: {len(factor_cols)}")
print(f"  数据行数: {len(df)}")
print(f"  因子列示例: {factor_cols[:10]}...")

print(f"\n{'='*60}")
print("✅ 第二阶段交付完成，待执行验证")
print("=" * 60)
