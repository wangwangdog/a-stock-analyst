import akshare as ak
import pandas as pd
import os
import re
from datetime import datetime

# 盘口异动数据，没有打开跌停和打开涨停
# ---------- 1. 所有异动分类 ----------
symbols = [
    '火箭发射', '快速反弹', '大笔买入', '封涨停板',
    '有大买盘', '竞价上涨', '高开5日线', '向上缺口', '60日新高',
    '60日大幅上涨', '加速下跌', '高台跳水', '大笔卖出', '封跌停板',
    '有大卖盘', '竞价下跌', '低开5日线', '向下缺口',
    '60日新低', '60日大幅下跌'
]
# '打开涨停板', '打开跌停板',

# ---------- 2. 输出文件夹 ----------
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
output_dir = os.path.join(PROJECT_DIR, '盘口异动_分类解析')
os.makedirs(output_dir, exist_ok=True)
date_tag = datetime.now().strftime('%Y%m%d')

print(f"输出目录: {output_dir}")
print(f"共 {len(symbols)} 个分类\n")

# ---------- 3. 逐类获取并解析 ----------
for sym in symbols:
    print(f'处理: {sym} ...', end=' ')
    try:
        df = ak.stock_changes_em(symbol=sym)
    except Exception as e:
        print(f'请求失败 ({e})')
        continue

    if df is None or df.empty:
        print('无数据')
        continue

    if '相关信息' not in df.columns or '时间' not in df.columns:
        print('缺少必要列，跳过')
        continue

    # 解析每一行的"相关信息"
    parsed_rows = []
    for _, row in df.iterrows():
        info = str(row['相关信息']).strip()
        if not info or info == 'nan':
            continue

        parts = [p.strip() for p in info.split(',')]
        if len(parts) < 3:
            continue

        # 提取数值（自动去掉非数字字符，保留负号）
        def extract_num(s):
            return float(re.sub(r'[^\d.\-]', '', s))

        try:
            qty = extract_num(parts[0])   # 买入数量
            price = extract_num(parts[1])  # 单价
            change = extract_num(parts[2]) # 涨跌幅
        except ValueError:
            continue

        amount = qty * price

        parsed_rows.append({
            '股票代码': row.get('代码', ''),
            '股票名称': row.get('名称', ''),
            '买入数量': qty,
            '单价': price,
            '涨跌幅': change,
            '金额(单价*数量)': amount,
            '买入时间': row['时间']
        })

    # 保存该类别的解析结果
    if parsed_rows:
        result_df = pd.DataFrame(parsed_rows).sort_values('买入时间')
        safe_name = sym.replace('/', '_')
        filename = f'盘口异动解析_{date_tag}_{safe_name}.xlsx'
        filepath = os.path.join(output_dir, filename)
        result_df.to_excel(filepath, index=False, engine='openpyxl')
        print(f'已生成 {len(parsed_rows)} 条明细')
    else:
        print('无有效解析数据')

print(f'\n✅ 完成！所有解析文件保存在：{output_dir}')
