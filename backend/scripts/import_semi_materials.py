#!/usr/bin/env python3
"""
半导体材料产业链入库脚本
- 查 A 股代码
- 创建分类
- 插入关系
"""
import sqlite3, json, sys
from pathlib import Path

CHAIN_DB = "/home/dogzi/.openclaw/workspace/a-stock-analyst/data/chain.db"
MAIN_DB = "/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/db/chanlun_klines.sqlite"

# ============================================================
# 数据定义：14 个品类 × 公司列表
# ============================================================
CATEGORIES = [
    ("semi_si_wafer", "硅片", "半导体硅片"),
    ("semi_specialty_gas", "电子特气", "半导体制造用特种气体"),
    ("semi_photomask", "掩模版", "光刻掩模版"),
    ("semi_cmp", "抛光材料", "CMP抛光垫/液/钻石碟"),
    ("semi_photoresist", "光刻胶", "半导体光刻胶及配套"),
    ("semi_sputter_target", "溅射靶材", "高纯溅射靶材"),
    ("semi_wet_chemical", "湿电子化学品", "湿电子化学品/电镀液"),
    ("semi_pma", "PMA电子级溶剂", "丙二醇甲醚醋酸酯"),
    ("semi_pfa", "PTFE/PFA氟材料", "高纯氟聚合物材料"),
    ("semi_pkg_substrate", "封装基板", "IC载板/封装基板"),
    ("semi_leadframe", "引线框架", "封装引线框架"),
    ("semi_emc", "环氧塑封料", "环氧塑封料/硅微粉"),
    ("semi_epoxy_resin", "环氧树脂", "电子级环氧树脂"),
    ("semi_hydrocarbon_resin", "碳氢树脂", "高频高速碳氢树脂"),
]

CATEGORY_MAP = {cid: (label, desc) for cid, label, desc in CATEGORIES}

# 每个品类下的公司（name, 备注）
COMPANIES = {
    "semi_si_wafer": [
        ("西安奕材", "半导体硅片全球市占率 6.87%，300mm核心供应商"),
        ("TCL中环", "全球市占率 6.77%，兼具半导体与太阳能硅片"),
        ("沪硅产业", "全球市占率 6.29%，大陆规模较大硅片企业"),
        ("立昂微", "全球市占率 2.9%，硅片+功率器件+化合物射频"),
        ("有研硅", "全球市占率 0.97%，刻蚀单晶硅领先"),
        ("神工股份", "刻蚀单晶硅A股第一，专注上游关键耗材"),
        ("中晶科技", "3-6英寸分立器件硅片全球~10%，6-8英寸起步"),
        ("上海合晶", "硅外延片营收13.21亿元，外延片核心供应商"),
    ],
    "semi_specialty_gas": [
        ("中船特气", "三氟化氮国内产能第一(12500吨)，覆盖多种特气"),
        ("昊华科技", "三氟化氮国内第二(5000吨)，PTFE第二，氟化工平台"),
        ("南大光电", "三氟化氮国内第三(4800吨)，光刻胶领先+MO源龙头"),
        ("金宏气体", "六氟丁二烯规划200吨，华东气体龙头"),
        ("华特气体", "六氟丁二烯规划130吨，覆盖主流晶圆厂"),
        ("广钢气体", "六氟丁二烯规划120吨，国内氦气领先"),
        ("和远气体", "六氟丁二烯规划50吨，湖北及新疆气源"),
        ("三孚股份", "二氯二氢硅A股第一(500吨)，已供货存储/逻辑"),
        ("华塑股份", "二氯二氢硅A股第二(500吨)，试生产阶段"),
        ("雅克科技", "四氟化碳A股第一(2000吨)，前驱体/光刻胶多材料"),
        ("凯美特气", "大宗气体0.39%，尾气回收提纯供应电子特气"),
    ],
    "semi_photomask": [
        ("龙图光罩", "半导体掩模版全球2%，国内领先"),
        ("冠石科技", "拟投资20亿元建设半导体掩模版项目"),
        ("清溢光电", "平板显示掩模版全球第五(6.6%)，拓展半导体"),
        ("路维光电", "平板显示掩模版全球第八(4.6%)，G11领先"),
        ("一彬科技", "入股上海传芯切入掩膜版，从汽车零部件跨界"),
    ],
    "semi_cmp": [
        ("鼎龙股份", "A股CMP抛光垫第一，打破海外垄断"),
        ("安集科技", "A股CMP抛光液第一，抛光液+垫一体化"),
        ("三超新材", "A股CMP钻石碟第一，用于CMP修整器"),
    ],
    "semi_photoresist": [
        ("彤程新材", "半导体光刻胶营收A股第一(7.45亿)，KrF/ArF品类覆盖"),
        ("南大光电", "光刻胶领先，同时MO源/电子特气多领域"),
        ("上海新阳", "光刻胶领先，电镀液/清洗液龙头"),
        ("晶瑞电材", "光刻胶领先，高纯双氧水/湿化学品"),
        ("容大感光", "光刻胶领先，PCB油墨市占率第二"),
        ("华懋科技", "光刻胶领先，从安全气囊跨界半导体材料"),
        ("雅克科技", "LCD光刻胶营收A股第一(15.35亿)"),
        ("飞凯材料", "LCD光刻胶营收A股第二(6.83亿)，紫外固化龙头"),
        ("广信材料", "PCB光刻胶营收A股第二(3.32亿)，PCB油墨第一"),
    ],
    "semi_sputter_target": [
        ("江丰电子", "靶材营收第一(28.5亿)，集成电路靶材龙头"),
        ("隆华科技", "靶材营收第二(7.82亿)，通过三星验证"),
        ("阿石创", "靶材营收第三(5.69亿)，PVD镀膜材料"),
        ("欧莱新材", "靶材营收第四(2.64亿)，高纯金属靶材"),
        ("有研新材", "产品包括靶材，稀土/高纯金属靶材供应商"),
    ],
    "semi_wet_chemical": [
        ("上海新阳", "电镀液全球第八(3%)，湿化学品龙头"),
        ("艾森股份", "电镀液全球第十一(1%)，电镀液及配套"),
        ("兴福电子", "电子级磷酸国内半导体第一(69%)，依托兴发集团"),
        ("江化微", "超净高纯试剂/光刻胶配套试剂综合供应商"),
        ("中巨芯", "电子级氢氟酸/硫酸/硝酸/盐酸/氨水平台"),
        ("格林达", "TMAH显影液龙头"),
        ("晶瑞电材", "高纯双氧水/硫化/氨水，湿化学品一体化"),
        ("盛剑科技", "光刻胶剥离液/蚀刻液/清洗液，从废气治理延伸"),
    ],
    "semi_pma": [
        ("怡达股份", "丙二醇甲醚乙酸酯国内第三"),
        ("百川股份", "丙二醇甲醚乙酸酯国内第四"),
    ],
    "semi_pfa": [
        ("巨化股份", "高纯PFA产能第一(5000吨)，氟化工龙头"),
        ("永和股份", "高纯PFA产能第二(3000吨)，氟化工新贵"),
        ("昊华科技", "高纯PFA产能第三(500吨)，有氟材料研发优势"),
        ("多氟多", "PFA下游流体输送配件加工"),
        ("三美股份", "PFA下游流体输送配件加工"),
    ],
    "semi_pkg_substrate": [
        ("兴森科技", "A股第一大封装基板上市公司"),
        ("深南电路", "A股第二大封装基板上市公司"),
    ],
    "semi_leadframe": [
        ("康强电子", "引线框架A股第一，全球4%"),
        ("新恒汇", "智能卡领域引线框架第一"),
    ],
    "semi_emc": [
        ("华海诚科", "环氧塑封料A股第一"),
        ("联瑞新材", "球形硅微粉国内第一(4.43万吨)，供货三星/海力士"),
        ("雅克科技", "球形硅微粉国内第二(2.25万吨)"),
        ("凌玮科技", "收购辉迈切入纳米级硅微粉"),
        ("元力股份", "拟收购福建同晟切入纳米级硅微粉"),
    ],
    "semi_epoxy_resin": [
        ("宏昌电子", "A股环氧树脂第一，国内6.5%"),
        ("同宇新材", "环氧树脂产能4.32万吨，特种研发突出"),
        ("圣泉集团", "环氧树脂产能2.72万吨，PPO树脂A股第一"),
    ],
    "semi_hydrocarbon_resin": [
        ("东材科技", "电子级碳氢树脂产能第一(3500吨)"),
        ("世名科技", "电子级碳氢树脂产能第二(500吨)"),
    ],
}

# ============================================================
# 1. 查 A 股代码
# ============================================================
def find_stock_codes():
    """从 stock_daily / all_stock_info 查公司代码"""
    conn = sqlite3.connect(MAIN_DB)
    
    # 方法1: all_stock_info 表（有 name 列）
    names = set()
    for company_list in COMPANIES.values():
        for name, _ in company_list:
            names.add(name)
    
    # 查询数据库
    results = {}
    try:
        rows = conn.execute("SELECT symbol, name FROM all_stock_info").fetchall()
        for sym, nm in rows:
            for name in names:
                # 精确匹配或包含关系
                if name == nm.strip() or name in nm or nm.strip() in name:
                    if name not in results:
                        results[name] = []
                    results[name].append(sym.strip())
    except Exception:
        pass
    
    conn.close()
    return results


def find_codes_from_stock_daily():
    """兜底：从 stock_daily 查 symbol（只有代码）"""
    import akshare as ak
    # 已知代码硬编码映射
    known_codes = {
        "TCL中环": "002129",
        "沪硅产业": "688126",
        "立昂微": "605358",
        "有研硅": "688432",
        "神工股份": "688233",
        "中晶科技": "003026",
        "上海合晶": "688584",
        "中船特气": "688146",
        "昊华科技": "600378",
        "南大光电": "300346",
        "金宏气体": "688106",
        "华特气体": "688268",
        "广钢气体": "688548",
        "和远气体": "002971",
        "三孚股份": "603938",
        "华塑股份": "600935",
        "雅克科技": "002409",
        "凯美特气": "002549",
        "龙图光罩": "688721",
        "冠石科技": "605588",
        "清溢光电": "688138",
        "路维光电": "688401",
        "一彬科技": "001278",
        "鼎龙股份": "300054",
        "安集科技": "688019",
        "三超新材": "300554",
        "彤程新材": "603650",
        "上海新阳": "300236",
        "晶瑞电材": "300655",
        "容大感光": "300576",
        "华懋科技": "603306",
        "飞凯材料": "300398",
        "广信材料": "300537",
        "江丰电子": "300666",
        "隆华科技": "300263",
        "阿石创": "300706",
        "欧莱新材": "688530",
        "有研新材": "600206",
        "艾森股份": "688720",
        "江化微": "603078",
        "中巨芯": "688549",
        "格林达": "603931",
        "盛剑科技": "603324",
        "怡达股份": "300721",
        "百川股份": "002455",
        "巨化股份": "600160",
        "永和股份": "605020",
        "多氟多": "002407",
        "三美股份": "603379",
        "兴森科技": "002436",
        "深南电路": "002916",
        "康强电子": "002119",
        "华海诚科": "688535",
        "联瑞新材": "688300",
        "凌玮科技": "301373",
        "元力股份": "300174",
        "宏昌电子": "603002",
        "圣泉集团": "605589",
        "东材科技": "601208",
        "世名科技": "300522",
        "西安奕材": "688560",
        "兴福电子": "688545",
        "同宇新材": "301269",
        "新恒汇": "301488",
    }
    return known_codes


# ============================================================
# 2. 建表 + 入库
# ============================================================
def init_chain_db():
    conn = sqlite3.connect(CHAIN_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chain_companies (
            code TEXT PRIMARY KEY,
            name TEXT,
            fullname TEXT,
            location TEXT,
            list_time TEXT
        );
        CREATE TABLE IF NOT EXISTS chain_overseas_entities (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            fullname TEXT,
            country TEXT
        );
        CREATE TABLE IF NOT EXISTS chain_supply_categories (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chain_supply_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_code TEXT NOT NULL REFERENCES chain_overseas_entities(code),
            buyer_name TEXT,
            supplier_code TEXT,
            supplier_name TEXT NOT NULL,
            category TEXT NOT NULL REFERENCES chain_supply_categories(id),
            coverage TEXT DEFAULT 'shared',
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_csr_buyer ON chain_supply_relations(buyer_code);
        CREATE INDEX IF NOT EXISTS idx_csr_supplier ON chain_supply_relations(supplier_name);
        CREATE INDEX IF NOT EXISTS idx_csr_cat ON chain_supply_relations(category);
        
        CREATE TABLE IF NOT EXISTS chain_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    
    # 创建虚拟海外实体：代表半导体材料采购方
    conn.execute("""
        INSERT OR IGNORE INTO chain_overseas_entities(code, name, fullname, country)
        VALUES ('SEMI_FAB', '半导体晶圆厂', 'Semiconductor Wafer Fab (材料采购方代表)', '全球')
    """)
    
    # 创建品类
    for cid, label, _ in CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO chain_supply_categories(id, label) VALUES (?, ?)",
                     (cid, label))
    
    # 创建大品类标签
    conn.execute("""
        INSERT OR IGNORE INTO chain_overseas_entities(code, name, fullname, country)
        VALUES ('SEMI_MAT', '半导体材料', 'Semiconductor Materials Supply Chain', '中国')
    """)
    
    conn.commit()
    return conn


def import_companies(conn, codes):
    """插入供应链关系"""
    total = 0
    errors = []
    for cid, company_list in COMPANIES.items():
        cat_label = CATEGORY_MAP[cid][0]
        for name, notes in company_list:
            code = codes.get(name, "")
            try:
                conn.execute(
                    """INSERT INTO chain_supply_relations 
                       (buyer_code, buyer_name, supplier_code, supplier_name, category, coverage, notes)
                       VALUES (?, ?, ?, ?, ?, 'shared', ?)""",
                    ("SEMI_FAB", "半导体晶圆厂", code, name, cid, notes)
                )
                total += 1
            except Exception as e:
                errors.append(f"{name}: {e}")
    conn.commit()
    return total, errors


def main():
    print("="*50)
    print("🔬 半导体材料产业链入库")
    print("="*50)
    
    # 查代码
    db_codes = find_stock_codes()
    known_codes = find_codes_from_stock_daily()
    
    # 合并：数据库查到的优先
    final_codes = {}
    for name in set().union(*COMPANIES.values()).union(*[list(c.keys()) for c in [known_codes]]):
        pass
    for name in [n for cl in COMPANIES.values() for n, _ in cl]:
        if name in db_codes and db_codes[name]:
            final_codes[name] = db_codes[name][0]
        elif name in known_codes:
            final_codes[name] = known_codes[name]
        else:
            final_codes[name] = ""
    
    print(f"\n📋 共 {len([n for cl in COMPANIES.values() for n,_ in cl])} 家公司")
    found = sum(1 for c in final_codes.values() if c)
    print(f"✅ 已找到代码: {found} 家")
    print(f"❌ 未找到代码: {sum(1 for c in final_codes.values() if not c)} 家")
    
    if found < 70:
        print("⚠️ 查找率不足，先确认...")
        for name, code in sorted(final_codes.items()):
            if not code:
                print(f"  缺代码: {name}")
    
    # 初始化数据库
    print("\n📦 建表...")
    conn = init_chain_db()
    
    # 导入
    print("\n🚀 导入数据...")
    total, errors = import_companies(conn, final_codes)
    print(f"✅ 成功插入 {total} 条关系")
    if errors:
        print(f"⚠️ 错误 {len(errors)} 条:")
        for e in errors[:10]:
            print(f"  {e}")
    
    # 验证
    print("\n📊 验证:")
    for cid, label, _ in CATEGORIES:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM chain_supply_relations WHERE category=? AND buyer_code='SEMI_FAB'",
            (cid,)
        ).fetchone()[0]
        if cnt > 0:
            print(f"  {label}: {cnt} 家公司")
    
    conn.close()
    print(f"\n✅ 入库完成！数据库: {CHAIN_DB}")


if __name__ == "__main__":
    main()
