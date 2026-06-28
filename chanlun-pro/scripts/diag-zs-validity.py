"""
中枢合理性诊断脚本 v2 - 带详细理由
用法: PYTHONPATH=src .venv/bin/python3 scripts/diag-zs-validity.py
"""
import sqlite3, pandas as pd, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config

def load_klines(symbol, freq, limit=7200):
    db = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
    conn = sqlite3.connect(db)
    if freq == 'd':
        df = pd.read_sql("SELECT date, open, high, low, close, volume, turnover as amount FROM stock_daily WHERE symbol=? ORDER BY date DESC LIMIT ?", conn, params=(symbol, limit))
    else:
        df = pd.read_sql(f"SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM a_klines_{symbol} WHERE f=? ORDER BY dt DESC LIMIT ?", conn, params=(freq, limit))
    conn.close()
    df = df.sort_values('date').reset_index(drop=True)
    return df

def check_zs(z, bis):
    lines = z.lines
    n = len(lines)
    if n < 3:
        return {'valid': False, 'checks': {}, 'reason': '笔数不足3, 不构成中枢'}

    b1, b_last = lines[0], lines[-1]
    mid = lines[1:-1]
    mid_highs = [b.high for b in mid]
    mid_lows = [b.low for b in mid]
    mid_zg = min(mid_highs)  # 中间笔顶部 = 最低的顶
    mid_zd = max(mid_lows)   # 中间笔底部 = 最高的底
    dirs = [l.type for l in lines]
    bi_indices = [l.index for l in lines]

    checks = {}

    # ① 中间笔重叠: ZG > ZD
    reason = (
        f"中间{len(mid)}笔高点:[{' '.join(f'{h:.2f}' for h in mid_highs)}] → "
        f"取最小值 ZG={mid_zg:.2f}\n"
        f"中间{len(mid)}笔低点:[{' '.join(f'{l:.2f}' for l in mid_lows)}] → "
        f"取最大值 ZD={mid_zd:.2f}\n"
    )
    if mid_zg > mid_zd:
        reason += f"ZG={mid_zg:.2f} > ZD={mid_zd:.2f}, 中间笔有重叠区间 ✅"
    else:
        reason += f"ZG={mid_zg:.2f} ≤ ZD={mid_zd:.2f}, 中间笔无重叠, 不构成中枢 ❌"
    checks['middle_overlap'] = {
        'pass': mid_zg > mid_zd,
        'detail': f'ZG={mid_zg:.2f} ZD={mid_zd:.2f}',
        'reason': reason,
    }

    # 如果中间笔不重叠, 后续检查无意义, 提前返回
    if not checks['middle_overlap']['pass']:
        all_pass = False
        fails = ['middle_overlap']
        return {'valid': False, 'checks': checks, 'reason': '中间笔不重叠, 不构成中枢'}

    # ② ZG/ZD 合理性: ZG 必须等于中间笔最低的high, ZD 必须等于中间笔最高的low
    zg_match = abs((z.zg or 0) - mid_zg) < 0.01
    zd_match = abs((z.zd or 0) - mid_zd) < 0.01
    if zg_match and zd_match:
        reason = "ZS.zg 与中间笔最低high一致✅, ZS.zd 与中间笔最高low一致✅"
    else:
        mismatch = []
        if not zg_match:
            mismatch.append(f"ZS.zg={z.zg:.2f} ≠ 中间笔minH={mid_zg:.2f}")
        if not zd_match:
            mismatch.append(f"ZS.zd={z.zd:.2f} ≠ 中间笔maxL={mid_zd:.2f}")
        reason = "; ".join(mismatch) + " ❌"
    checks['zgzd_correct'] = {
        'pass': zg_match and zd_match,
        'detail': f'ZS.zg={z.zg:.2f} mid_minH={mid_zg:.2f}  ZS.zd={z.zd:.2f} mid_maxL={mid_zd:.2f}',
        'reason': reason,
    }

    # ③ 笔方向交替
    alt_pass = all(dirs[i] != dirs[i+1] for i in range(n-1))
    if alt_pass:
        reason = f"方向严格交替: {'→'.join(dirs)} ✅"
    else:
        bad = [f"{i}-{i+1}笔同向({dirs[i]})" for i in range(n-1) if dirs[i] == dirs[i+1]]
        reason = f"相邻笔方向重复: {', '.join(bad)} ❌"
    checks['alternate'] = {
        'pass': alt_pass,
        'detail': '→'.join(dirs),
        'reason': reason,
    }

    # ④ 进入笔从外入场
    entry_start = b1.start.val
    if z.type == 'up':
        entry_check = entry_start < mid_zd
        if entry_check:
            reason = f"上涨中枢, 进入笔起点{entry_start:.2f} < ZD={mid_zd:.2f}, 从下方入场 ✅"
        else:
            reason = f"上涨中枢, 进入笔起点{entry_start:.2f} ≥ ZD={mid_zd:.2f}, 起点在中枢内部, 入场不合理 ❌"
    else:
        entry_check = entry_start > mid_zg
        if entry_check:
            reason = f"下跌中枢, 进入笔起点{entry_start:.2f} > ZG={mid_zg:.2f}, 从上方入场 ✅"
        else:
            reason = f"下跌中枢, 进入笔起点{entry_start:.2f} ≤ ZG={mid_zg:.2f}, 起点在中枢内部, 入场不合理 ❌"
    checks['entry_outside'] = {
        'pass': entry_check,
        'detail': f'entry_start={entry_start:.2f}  ZG={mid_zg:.2f}  ZD={mid_zd:.2f}',
        'reason': reason,
    }

    # ⑤ 离开笔突破出场
    exit_end = b_last.end.val
    if z.type == 'up':
        exit_check = exit_end > mid_zg
        if exit_check:
            reason = f"上涨中枢, 离开笔终点{exit_end:.2f} > ZG={mid_zg:.2f}, 向上突破 ✅"
        else:
            reason = f"上涨中枢, 离开笔终点{exit_end:.2f} ≤ ZG={mid_zg:.2f}, 未突破框体 ❌"
    else:
        exit_check = exit_end < mid_zd
        if exit_check:
            reason = f"下跌中枢, 离开笔终点{exit_end:.2f} < ZD={mid_zd:.2f}, 向下突破 ✅"
        else:
            reason = f"下跌中枢, 离开笔终点{exit_end:.2f} ≥ ZD={mid_zd:.2f}, 未突破框体 ❌"
    checks['exit_break'] = {
        'pass': exit_check,
        'detail': f'exit_end={exit_end:.2f}  ZG={mid_zg:.2f}  ZD={mid_zd:.2f}',
        'reason': reason,
    }

    # ⑥ 振幅阈值
    if z.gg and z.dd and mid_zd:
        amp = (z.gg - z.dd) / mid_zd * 100
        amp_pass = amp > 0.1
        if amp_pass:
            reason = f"振幅={amp:.3f}% > 0.1%, 中枢有足够波幅 ✅"
        else:
            reason = f"振幅={amp:.3f}% ≤ 0.1%, 波幅过窄, 可能是噪声 ❌"
    else:
        amp, amp_pass = 0, False
        reason = "无振幅数据 ❌"
    checks['amplitude'] = {
        'pass': amp_pass,
        'detail': f'GG={z.gg:.2f} DD={z.dd:.2f} 振幅={amp:.3f}%',
        'reason': reason,
    }

    # ⑦ 跨度合理
    span = max(bi_indices) - min(bi_indices)
    span_pass = span < 20
    if span_pass:
        reason = f"BI跨度={span}笔 < 20, 延伸范围合理 ✅"
    else:
        reason = f"BI跨度={span}笔 ≥ 20, 延伸过度, 可能合并了多个中枢 ❌"
    checks['span'] = {
        'pass': span_pass,
        'detail': f'BI索引 {min(bi_indices)}~{max(bi_indices)} 跨度={span}笔',
        'reason': reason,
    }

    all_pass = all(c['pass'] for c in checks.values())
    fails = [(k, c['reason'].split('❌')[0].strip()) for k, c in checks.items() if not c['pass']]
    fail_detail = '; '.join([f"{k}: {r}" for k, r in fails])

    return {
        'valid': all_pass,
        'checks': checks,
        'reason': '全部通过 ✅' if all_pass else f'不通过({len(fails)}项): {fail_detail}',
    }


def main():
    symbol = '000001'
    freq = '5m'

    df = load_klines(symbol, freq)
    print(f'K线: {len(df)} 条')

    cfg = query_cl_chart_config('a', symbol)
    cd = CD(symbol, freq, config=cfg)
    cd.process_klines(df)
    bis = cd.get_bis()
    zss = cd.get_bi_zss()

    print(f'BI={len(bis)}, ZS={len(zss)}\n')

    valid_count = 0
    invalid_count = 0

    for z in zss:
        dir_str = '→'.join([l.type for l in z.lines])
        result = check_zs(z, bis)
        status = '✅' if result['valid'] else '❌'

        print(f'\nZS #{z.index} ({len(z.lines)}笔 {dir_str}) {status}')
        print(f'  方向: {z.type}中枢  笔索引: {[l.index for l in z.lines]}')
        for k, c in result['checks'].items():
            mark = '✅' if c['pass'] else '❌'
            print(f'  {mark} [{k}]')
            for line in c['reason'].split('\n'):
                print(f'       {line}')

        if result['valid']:
            valid_count += 1
        else:
            invalid_count += 1
            print(f'  结论: {result["reason"]}')

    print(f'\n{"="*50}')
    print(f'合理: {valid_count}, 不合理: {invalid_count}, 总计: {len(zss)}')
    print(f'合理率: {valid_count/len(zss)*100:.0f}%')


if __name__ == '__main__':
    main()
