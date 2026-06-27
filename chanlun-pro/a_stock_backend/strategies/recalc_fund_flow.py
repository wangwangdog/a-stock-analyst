"""
重算所有 stock_fund_flow_local 数据（用新公式：方向由涨跌决定）
"""
import sys
import time
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/a_stock_backend')
from data.cache import _get_conn
from strategies.fund_flow_collector import _compute_from_local, _save_records_local

# 分页读取symbol，避免一次性加载所有
conn = _get_conn()
total = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period='daily' AND source='tencent_fq' AND symbol NOT LIKE '%.%' AND substr(symbol,1,1) IN ('0','3','6','9')").fetchone()[0]
print(f"共 {total} 只股票需要重算", flush=True)

offset = 0
batch = 200
ok, fail = 0, 0

while True:
    conn = _get_conn()
    batch_syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND source='tencent_fq' "
        "AND symbol NOT LIKE '%.%' AND substr(symbol,1,1) IN ('0','3','6','9') "
        "ORDER BY symbol LIMIT ? OFFSET ?",
        (batch, offset)
    ).fetchall()]
    conn.close()

    if not batch_syms:
        break

    for sym in batch_syms:
        try:
            # 删旧数据
            conn = _get_conn()
            conn.execute("DELETE FROM stock_fund_flow_local WHERE symbol=?", (sym,))
            conn.commit()
            conn.close()

            # 重算
            records = _compute_from_local(sym, 100)
            if records:
                cnt = _save_records_local(sym, records)
                inflow = sum(1 for r in records if r['main_inflow'] > 0)
                outflow = len(records) - inflow
            else:
                cnt = 0
                inflow = outflow = 0
            ok += 1

            if (ok + fail) % 100 == 0:
                print(f"  [{ok+fail}/{total}] {sym} → {len(records)}条 ({inflow}↑/{outflow}↓) 成功:{ok} 失败:{fail}", flush=True)

            time.sleep(0.02)

        except Exception as e:
            fail += 1
            print(f"  ❌ {sym}: {e}", flush=True)

    offset += batch
    print(f"  --- 批次完成, 已处理 {offset}/{total}, 成功:{ok} 失败:{fail} ---", flush=True)

print(f"\n✅ 全部完成! 成功 {ok}, 失败 {fail}", flush=True)
