"""
产业链突破引擎 — 新闻驱动 · 概念传导 · 供应链智能

三层架构：
  Layer 1: 新闻→实体抽取（公司名/产品/概念关键词匹配）
  Layer 2: 概念热度传导（涨停热榜 → 概念板块 → 供应链上下游）
  Layer 3: 供应链事件联动（新闻事件 → 匹配产业链节点 → 高亮影响链）
"""
import re, json, sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"


def get_conn():
    return sqlite3.connect(DB_PATH)


# ══════════════════════════════════════════════
# 数据源：已有表
# ══════════════════════════════════════════════

def get_concept_stocks(concept_name: str) -> list[str]:
    """获取某概念下的所有股票"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT code FROM stock_concept WHERE concept_name=? AND category='GN'",
        (concept_name,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_stock_concepts(code: str) -> list[dict]:
    """获取股票所属的所有概念"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT concept_name, category FROM stock_concept WHERE code=?",
        (code,)
    ).fetchall()
    conn.close()
    return [{"name": r[0], "category": r[1]} for r in rows]


def get_industry_chain_pairs() -> list[dict]:
    """获取产业链上下游关系（从 chain_supply_relations + chain_company_product）"""
    conn = get_conn()
    pairs = []
    
    # 供应链上下游关系
    try:
        rows = conn.execute(
            "SELECT buyer_code, buyer_name, supplier_code, supplier_name, category, notes "
            "FROM chain_supply_relations LIMIT 5000"
        ).fetchall()
        for r in rows:
            pairs.append({
                "buyer_code": r[0], "buyer_name": r[1],
                "supplier_code": r[2], "supplier_name": r[3],
                "category": r[4], "notes": r[5],
            })
    except Exception as e:
        print(f"[WARN] chain_supply_relations: {e}")
    
    # 公司→产品关系（可反向推导产品上下游）
    try:
        rows = conn.execute(
            "SELECT company_code, company_name, product_name, rel "
            "FROM chain_company_product LIMIT 5000"
        ).fetchall()
        for r in rows:
            pairs.append({
                "company_code": r[0], "company_name": r[1],
                "product": r[2], "rel": r[3],
                "type": "product_relation",
            })
    except Exception as e:
        print(f"[WARN] chain_company_product: {e}")
    
    conn.close()
    return pairs


# ══════════════════════════════════════════════
# Layer 1: 新闻→实体抽取
# ══════════════════════════════════════════════

# A股知名公司名称→代码映射（核心池）
STOCK_NAME_MAP = {
    "贵州茅台": "SH.600519", "茅台": "SH.600519",
    "宁德时代": "SZ.300750", "宁德": "SZ.300750",
    "中国平安": "SH.601318",
    "招商银行": "SH.600036",
    "比亚迪": "SZ.002594",
    "五粮液": "SZ.000858",
    "美的集团": "SZ.000333",
    "恒瑞医药": "SH.600276",
    "隆基绿能": "SH.601012", "隆基": "SH.601012",
    "药明康德": "SH.603259",
    "中信证券": "SH.600030",
    "立讯精密": "SZ.002475",
    "迈瑞医疗": "SZ.300760",
    "海康威视": "SZ.002415",
    "中芯国际": "SH.688981",
    "紫金矿业": "SH.601899",
    "工业富联": "SH.601138",
    "阳光电源": "SZ.300274",
    "格力电器": "SZ.000651",
    "长江电力": "SH.600900",
    "海尔智家": "SH.600690",
    "万华化学": "SH.600309",
    "京东方A": "SZ.000725", "京东方": "SZ.000725",
    "中际旭创": "SZ.300308",
    "科大讯飞": "SZ.002230",
    "赛力斯": "SH.601127",
    "中兴通讯": "SZ.000063",
    "东方财富": "SZ.300059",
}


def extract_entities_from_news(title: str, content: str = "") -> dict:
    """从新闻标题+内容中抽取实体（公司/概念/产品）"""
    text = f"{title} {content}"
    entities = {"companies": [], "concepts": [], "products": []}
    
    # 匹配公司名
    for name, code in STOCK_NAME_MAP.items():
        if name in text and len(name) >= 2:
            entities["companies"].append({"name": name, "code": code})
    
    # 匹配热门概念关键词
    concepts = get_hot_concept_keywords()
    for cname in concepts:
        if cname in text:
            entities["concepts"].append({"name": cname})
    
    # 匹配产业链产品/原材料关键词
    products = get_product_keywords()
    for pname in products:
        if pname in text:
            entities["products"].append({"name": pname})
    
    return entities


def get_hot_concept_keywords() -> list[str]:
    """从 stock_concept 表提取活跃概念名称"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT concept_name FROM stock_concept WHERE category='GN' ORDER BY concept_name"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_product_keywords() -> list[str]:
    """从产业链表中提取产品关键词"""
    conn = get_conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    
    keywords = set()
    if 'material_flows_ts' in tables:
        rows = conn.execute(
            "SELECT DISTINCT category FROM material_flows_ts WHERE category IS NOT NULL AND category!=''"
        ).fetchall()
        for r in rows:
            if r[0] and len(r[0]) >= 2:
                keywords.add(r[0])
    
    if 'chain_supply_categories' in tables:
        rows = conn.execute(
            "SELECT DISTINCT name FROM chain_supply_categories WHERE name IS NOT NULL"
        ).fetchall()
        for r in rows:
            if r[0] and len(r[0]) >= 2:
                keywords.add(r[0])
    
    conn.close()
    return list(keywords)


# ══════════════════════════════════════════════
# Layer 2: 概念热度传导
# ══════════════════════════════════════════════

def get_latest_zt_stocks(limit: int = 50) -> list[dict]:
    """获取最新涨停股票列表"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT code, name, limit_days, zt_stat, industry, seal_fund "
        "FROM limit_up_pool WHERE pool_type='zt' "
        "ORDER BY trade_date DESC, limit_days DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"code": r[0], "name": r[1], "limit_days": r[2],
             "zt_stat": r[3], "industry": r[4], "seal_fund": r[5]}
            for r in rows]


def get_hot_concepts_from_limit_up(limit: int = 10) -> list[dict]:
    """从涨停板反向推导热门概念（涨停股票所属概念的热度排行）"""
    zt_stocks = get_latest_zt_stocks(50)
    
    concept_heat = {}
    for s in zt_stocks:
        concepts = get_stock_concepts(s["code"])
        for c in concepts:
            if c["category"] == "GN":
                name = c["name"]
                if name not in concept_heat:
                    concept_heat[name] = {"zt_count": 0, "total_limit_days": 0, "stocks": []}
                concept_heat[name]["zt_count"] += 1
                concept_heat[name]["total_limit_days"] += (s["limit_days"] or 1)
                concept_heat[name]["stocks"].append(s["code"])
    
    # 排序：涨停数量多 → 连板数高 → 靠前
    sorted_concepts = sorted(
        concept_heat.items(),
        key=lambda x: (x[1]["zt_count"], x[1]["total_limit_days"]),
        reverse=True
    )
    return [{"concept": k, "zt_count": v["zt_count"],
             "total_limit_days": v["total_limit_days"],
             "stocks": v["stocks"]}
            for k, v in sorted_concepts[:limit]]


def get_industry_heat_from_limit_up(limit: int = 10) -> list[dict]:
    """从涨停板看行业热度"""
    zt_stocks = get_latest_zt_stocks(50)
    industry_heat = {}
    for s in zt_stocks:
        ind = s.get("industry", "未知") or "未知"
        if ind not in industry_heat:
            industry_heat[ind] = {"zt_count": 0, "stocks": []}
        industry_heat[ind]["zt_count"] += 1
        industry_heat[ind]["stocks"].append(s["code"])
    
    sorted_inds = sorted(
        industry_heat.items(),
        key=lambda x: x[1]["zt_count"],
        reverse=True
    )
    return [{"industry": k, "zt_count": v["zt_count"], "stocks": v["stocks"]}
            for k, v in sorted_inds[:limit]]


# ══════════════════════════════════════════════
# Layer 3: 供应链事件联动
# ══════════════════════════════════════════════

def find_impacted_suppliers(company_code: str) -> list[dict]:
    """查找某公司的供应链上下游，从 chain_supply_relations 查询"""
    conn = get_conn()
    
    # 查找公司名（用带代码前缀的匹配）
    impacted = []
    
    try:
        # 下游：该公司是 buyer，找它的 suppliers
        rows = conn.execute(
            "SELECT buyer_name, supplier_code, supplier_name, category, notes "
            "FROM chain_supply_relations WHERE buyer_code=? OR buyer_code=?",
            (company_code, company_code.replace("SH.","").replace("SZ.","").replace("BJ.",""))
        ).fetchall()
        for r in rows:
            impacted.append({
                "direction": "upstream",  # buyer 的上游是 supplier
                "target_code": r[1], "target_name": r[2],
                "category": r[3], "notes": r[4],
            })
        
        # 上游：该公司是 supplier，找它的 buyers
        rows = conn.execute(
            "SELECT buyer_code, buyer_name, supplier_name, category, notes "
            "FROM chain_supply_relations WHERE supplier_code=? OR supplier_code=?",
            (company_code, company_code.replace("SH.","").replace("SZ.","").replace("BJ.",""))
        ).fetchall()
        for r in rows:
            impacted.append({
                "direction": "downstream",  # supplier 的下游是 buyer
                "target_code": r[0], "target_name": r[1],
                "category": r[3], "notes": r[4],
            })
    except Exception as e:
        print(f"[WARN] find_impacted_suppliers: {e}")
    
    conn.close()
    return impacted


def news_chain_impact_analysis(news_title: str, news_content: str = "") -> dict:
    """新闻产业链影响分析：输入新闻 → 输出影响的产业链节点 + 关联股票"""
    entities = extract_entities_from_news(news_title, news_content)
    
    result = {
        "entities": entities,
        "direct_impact": [],
        "chain_impact": [],
        "related_concepts": [],
    }
    
    # 直接影响的公司
    for c in entities["companies"]:
        result["direct_impact"].append({
            "code": c["code"],
            "name": c["name"],
            "source": "新闻直接提及",
        })
        # 供应链传播
        chain = find_impacted_suppliers(c["code"])
        result["chain_impact"].extend(chain)
    
    # 概念关联
    for c in entities["concepts"]:
        stocks = get_concept_stocks(c["name"])
        result["related_concepts"].append({
            "concept": c["name"],
            "stocks": stocks[:10],
        })
    
    return result


# ══════════════════════════════════════════════
# 综合报告
# ══════════════════════════════════════════════

def generate_market_snapshot() -> dict:
    """生成市场全景快照（产业链视角）"""
    now = datetime.now()
    
    # 涨停热点 → 概念传导
    hot_concepts = get_hot_concepts_from_limit_up(10)
    industry_heat = get_industry_heat_from_limit_up(10)
    
    # 龙虎榜资金流向
    conn = get_conn()
    top_dragon = conn.execute(
        "SELECT code, name, net_buy, trade_date FROM dragon_tiger "
        "ORDER BY ABS(net_buy) DESC LIMIT 10"
    ).fetchall()
    conn.close()
    
    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M"),
        "hot_concepts": hot_concepts,
        "industry_heat": industry_heat,
        "top_dragon_tiger": [
            {"code": r[0], "name": r[1], "net_buy": r[2], "date": r[3]}
            for r in top_dragon
        ],
        "chain_alerts": generate_chain_alerts(),
    }


def generate_chain_alerts() -> list[dict]:
    """生成产业链预警（单点依赖风险 + 上下游集中度）"""
    alerts = []
    conn = get_conn()
    
    try:
        # 统计每个供应商被多少买家依赖
        rows = conn.execute(
            "SELECT supplier_name, supplier_code, COUNT(DISTINCT buyer_code) AS cnt "
            "FROM chain_supply_relations "
            "WHERE supplier_code IS NOT NULL AND supplier_code != '' "
            "GROUP BY supplier_code "
            "HAVING cnt >= 3 "
            "ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        for r in rows:
            alerts.append({
                "type": "高集中度",
                "supplier": r[0],
                "supplier_code": r[1],
                "dependent_count": r[2],
                "severity": "high" if r[2] >= 5 else "medium",
            })
    except Exception as e:
        print(f"[WARN] generate_chain_alerts: {e}")
    
    conn.close()
    return alerts


# ══════════════════════════════════════════════
# 建表：产业链分析缓存
# ══════════════════════════════════════════════

CREATE_CHAIN_ANALYSIS_CACHE = """
CREATE TABLE IF NOT EXISTS chain_analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_hash TEXT NOT NULL UNIQUE,
    news_title TEXT,
    news_time TEXT,
    entities TEXT,
    direct_impact TEXT,
    chain_impact TEXT,
    related_concepts TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def init_chain_tables():
    conn = get_conn()
    conn.execute(CREATE_CHAIN_ANALYSIS_CACHE)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_chain_tables()
    
    # 测试
    snapshot = generate_market_snapshot()
    print(f"🔥 热门概念 TOP5:")
    for c in snapshot["hot_concepts"][:5]:
        print(f"  {c['concept']}: {c['zt_count']}只涨停")
    
    print(f"\n🏭 热门行业 TOP5:")
    for ind in snapshot["industry_heat"][:5]:
        print(f"  {ind['industry']}: {ind['zt_count']}只涨停")
    
    print(f"\n⚠️ 产业链预警:")
    for a in snapshot["chain_alerts"]:
        print(f"  [{a['severity']}] {a['supplier']} 被 {a['dependent_count']} 家依赖")
    
    print(f"\n✅ 产业链引擎初始化完成")
