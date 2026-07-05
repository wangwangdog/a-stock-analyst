"""
API 路由 - 产业链数据查询

基于 ChainKnowledgeGraph 数据提供:
  - 公司上下游产业链
  - 同行业公司
  - 产品上下游关系
  - 消息列表面（大单+事件聚合）
"""
import sqlite3
import json
import os
import re
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/v1", tags=["产业链"])

logger = logging.getLogger("chain_route")

# 数据库路径
_main_db = Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite")


def _get_chain_conn():
    """获取产业链数据库连接（主库）"""
    conn = sqlite3.connect(str(_main_db))
    conn.row_factory = sqlite3.Row
    return conn


def _check_chain_db():
    """检查产业链数据库是否已导入"""
    if not _main_db.exists():
        raise HTTPException(503, detail="主数据库不存在")
    conn = sqlite3.connect(str(_main_db))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chain_companies', 'chain_supply_relations')"
    ).fetchall()]
    conn.close()
    if 'chain_companies' not in tables:
        raise HTTPException(503, detail="产业链数据库未就绪，请先运行 chain_import")
    return str(_main_db)


# ===== 产业链查询 API =====

@router.get("/chain/stock/{code}")
async def get_chain_for_stock(code: str):
    """
    获取股票的完整产业链数据
    
    返回: 公司信息、所属行业、主营产品、上游原材料、下游产品、同行业公司
    """
    _check_chain_db()
    conn = _get_chain_conn()
    
    try:
        # 1. 公司基本信息
        company = conn.execute(
            "SELECT * FROM chain_companies WHERE code = ?", (code,)
        ).fetchone()
        
        if not company:
            # 尝试模糊匹配
            company = conn.execute(
                "SELECT * FROM chain_companies WHERE code LIKE ?", (f"%{code}%",)
            ).fetchone()
        
        if not company:
            return {"code": code, "status": "not_found", "message": "该公司不在产业链数据库中"}
        
        result = {
            "code": company["code"],
            "name": company["name"],
            "fullname": company["fullname"],
            "location": company["location"],
            "list_time": company["list_time"],
        }
        
        # 2. 所属行业
        industries = conn.execute(
            "SELECT industry_code, industry_name FROM chain_company_industry WHERE company_code = ?",
            (code,)
        ).fetchall()
        result["industries"] = [{"code": r["industry_code"], "name": r["industry_name"]} for r in industries]
        
        # 3. 主营产品
        products = conn.execute(
            "SELECT product_name, rel FROM chain_company_product WHERE company_code = ? LIMIT 50",
            (code,)
        ).fetchall()
        result["main_products"] = [{"name": r["product_name"], "relation": r["rel"]} for r in products]
        
        # 4. 上游原材料（通过产品链路）
        product_names = [r["product_name"] for r in products]
        upstream_relations = set()
        if product_names:
            placeholders = ",".join("?" * len(product_names))
            upstream_rows = conn.execute(
                f"SELECT DISTINCT to_entity, from_entity FROM chain_product_relation WHERE rel='上游材料' AND from_entity IN ({placeholders}) LIMIT 100",
                product_names
            ).fetchall()
            for r in upstream_rows:
                upstream_relations.add((r["from_entity"], r["to_entity"]))
        result["upstream"] = [{"product": p, "material": m} for p, m in upstream_relations]
        
        # 5. 下游产品
        downstream_relations = set()
        if product_names:
            placeholders = ",".join("?" * len(product_names))
            # 公司产品作为原材料被下游使用
            downstream_rows = conn.execute(
                f"SELECT DISTINCT from_entity, to_entity FROM chain_product_relation WHERE rel='下游产品' AND to_entity IN ({placeholders}) LIMIT 100",
                product_names
            ).fetchall()
            for r in downstream_rows:
                downstream_relations.add((r["from_entity"], r["to_entity"]))
        result["downstream"] = [{"product": prod, "uses": mat} for prod, mat in downstream_relations]
        
        # 6. 同行业公司
        peers = conn.execute(
            "SELECT peer_code, peer_name, industry_name FROM chain_same_industry WHERE company_code = ? LIMIT 20",
            (code,)
        ).fetchall()
        result["peers"] = [
            {"code": p["peer_code"], "name": p["peer_name"], "industry": p["industry_name"]}
            for p in peers
        ]
        
        # 7. 完整的图数据（节点+边，供前端可视化）
        nodes = []
        edges = []
        node_ids = set()
        
        def add_node(nid, label, ntype, props=None):
            if nid not in node_ids:
                node_ids.add(nid)
                node = {"id": nid, "label": label, "type": ntype}
                if props:
                    node.update(props)
                nodes.append(node)
        
        def add_edge(source, target, rel_label, rel_type=""):
            edges.append({
                "source": source,
                "target": target,
                "label": rel_label,
                "type": rel_type,
            })
        
        # 公司节点
        add_node(code, company["name"], "company", {"fullname": company["fullname"]})
        
        # 行业节点
        for ind in result["industries"]:
            add_node(f"ind_{ind['code']}", ind["name"], "industry")
            add_edge(code, f"ind_{ind['code']}", "所属行业", "company_industry")
        
        # 产品节点
        for prod in products:
            pname = prod["product_name"]
            pid = f"prod_{pname}"
            add_node(pid, pname, "product")
            add_edge(code, pid, "主营产品", "company_product")
        
        # 上游边
        for up in upstream_relations:
            mid = f"mat_{up[1]}"
            pid = f"prod_{up[0]}"
            add_node(mid, up[1], "material")
            add_edge(pid, mid, "上游原材料", "upstream")
        
        # 下游边
        for down in downstream_relations:
            did = f"down_{down[0]}"
            pid = f"prod_{down[1]}"
            add_node(did, down[0], "downstream_product")
            add_edge(did, pid, "下游使用", "downstream")
        
        result["graph"] = {"nodes": nodes, "edges": edges}
        result["status"] = "ok"
        
        return result
        
    finally:
        conn.close()


@router.get("/chain/industry/{industry_name}")
async def get_companies_in_industry(industry_name: str, limit: int = 50):
    """获取某行业下的所有上市公司"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT company_code, company_name FROM chain_company_industry WHERE industry_name LIKE ? LIMIT ?",
            (f"%{industry_name}%", limit)
        ).fetchall()
        return {
            "industry": industry_name,
            "companies": [{"code": r["company_code"], "name": r["company_name"]} for r in rows],
            "count": len(rows),
        }
    finally:
        conn.close()


@router.get("/chain/product/{product_name}")
async def get_product_chain(product_name: str):
    """获取产品的上下游关系"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        # 上游
        upstream = conn.execute(
            "SELECT DISTINCT to_entity FROM chain_product_relation WHERE rel='上游材料' AND from_entity LIKE ? LIMIT 50",
            (f"%{product_name}%",)
        ).fetchall()
        
        # 下游
        downstream = conn.execute(
            "SELECT DISTINCT from_entity FROM chain_product_relation WHERE rel='下游产品' AND to_entity LIKE ? LIMIT 50",
            (f"%{product_name}%",)
        ).fetchall()
        
        # 小类
        subtypes = conn.execute(
            "SELECT DISTINCT from_entity FROM chain_product_relation WHERE rel='产品小类' AND to_entity LIKE ? LIMIT 50",
            (f"%{product_name}%",)
        ).fetchall()
        
        # 生产该产品的公司
        companies = conn.execute(
            "SELECT DISTINCT company_code, company_name FROM chain_company_product WHERE product_name LIKE ? LIMIT 20",
            (f"%{product_name}%",)
        ).fetchall()
        
        return {
            "product": product_name,
            "upstream_materials": [r["to_entity"] for r in upstream],
            "downstream_users": [r["from_entity"] for r in downstream],
            "subtypes": [r["from_entity"] for r in subtypes],
            "producers": [{"code": r["company_code"], "name": r["company_name"]} for r in companies],
        }
    finally:
        conn.close()


@router.get("/chain/search")
async def search_chain(q: str = Query(..., min_length=1, description="搜索关键词"), limit: int = 20):
    """搜索产业链中的公司/产品/行业"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        like = f"%{q}%"
        results = []
        
        # 搜公司
        companies = conn.execute(
            "SELECT code, name, fullname FROM chain_companies WHERE name LIKE ? OR fullname LIKE ? OR code LIKE ? LIMIT ?",
            (like, like, like, limit)
        ).fetchall()
        for r in companies:
            results.append({"type": "company", "code": r["code"], "name": r["name"], "fullname": r["fullname"]})
        
        # 搜产品
        if len(results) < limit:
            products = conn.execute(
                "SELECT DISTINCT product_name FROM chain_company_product WHERE product_name LIKE ? LIMIT ?",
                (like, limit - len(results))
            ).fetchall()
            for r in products:
                results.append({"type": "product", "name": r["product_name"]})
        
        # 搜行业
        if len(results) < limit:
            industries = conn.execute(
                "SELECT DISTINCT industry_name FROM chain_company_industry WHERE industry_name LIKE ? LIMIT ?",
                (like, limit - len(results))
            ).fetchall()
            for r in industries:
                results.append({"type": "industry", "name": r["industry_name"]})
        
        return {"query": q, "results": results, "count": len(results)}
    finally:
        conn.close()


# ===== 消息列表 API =====

@router.get("/messages")
async def get_messages(days: int = Query(7, ge=1, le=30, description="最近N天")):
    """
    获取首页消息列表
    
    聚合来源:
    1. 大单买入事件
    2. 最近查看的股票
    （后续扩展: Graphify 研报处理结果）
    """
    messages = []
    
    # 1. 大单买入事件（从现有 bigbuy 表）
    try:
        main_conn = sqlite3.connect(str(_main_db))
        main_conn.row_factory = sqlite3.Row
        
        # 检查表是否存在
        tables = main_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('big_deal_summary', 'stock_fund_flow')"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        
        if "big_deal_summary" in table_names:
            # 最近N天的大单汇总
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = main_conn.execute(
                """SELECT DISTINCT symbol, trade_date, buy_amount, sell_amount, net_amount
                   FROM big_deal_summary
                   WHERE trade_date >= ?
                   ORDER BY trade_date DESC LIMIT 30""",
                (cutoff,)
            ).fetchall()
            
            for r in rows:
                net = r["net_amount"] or 0
                if net > 0:
                    direction = "净流入"
                    amount_text = f"{net/10000:.0f}万"
                else:
                    direction = "净流出"
                    amount_text = f"{-net/10000:.0f}万"
                
                messages.append({
                    "id": f"bigdeal_{r['symbol']}_{r['trade_date']}",
                    "type": "big_deal",
                    "symbol": r["symbol"],
                    "date": r["trade_date"],
                    "title": f"{direction} {amount_text}",
                    "summary": f"{r['trade_date']} 大单{r['buy_amount']/10000:.0f}万买 / {r['sell_amount']/10000:.0f}万卖",
                    "action": "view_chain",
                    "action_target": r["symbol"],
                })
        
        main_conn.close()
    except Exception as e:
        pass  # 大单数据不可用时静默跳过
    
    # 2. 如消息不足，补充"探索产业链"入口
    if len(messages) < 5:
        messages.append({
            "id": "explore_1",
            "type": "system",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": "🔍 探索产业链图谱",
            "summary": "查看 A 股上市公司上下游产业链关系",
            "action": "search_chain",
            "action_target": "",
        })
        messages.append({
            "id": "explore_2",
            "type": "system",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": "📊 行业热度",
            "summary": "查看申万行业分类及各行业上市公司分布",
            "action": "industry_list",
            "action_target": "",
        })
    
    return {"messages": messages, "count": len(messages)}


@router.get("/chain/industry-list")
async def list_industries():
    """列出所有行业分类"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        rows = conn.execute(
            """SELECT ci.industry_name, COUNT(DISTINCT ci.company_code) as company_count
               FROM chain_company_industry ci
               GROUP BY ci.industry_name
               ORDER BY company_count DESC LIMIT 100"""
        ).fetchall()
        return {
            "industries": [
                {"name": r["industry_name"], "company_count": r["company_count"]}
                for r in rows
            ]
        }
    finally:
        conn.close()


# ===== 全球物质流数据 API (v2) =====

@router.get("/chain/material-flows/countries")
def list_material_flow_countries():
    """列出有全球物质流数据的国家"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        rows = conn.execute(
            "SELECT name, COUNT(*) as flows FROM global_entities ge "
            "JOIN material_flows_ts mf ON ge.id = mf.entity_id "
            "WHERE ge.type='country' AND ge.source='material_flows' "
            "GROUP BY ge.id ORDER BY flows DESC"
        ).fetchall()
        return {
            "total": len(rows),
            "countries": [{"name": r["name"], "data_points": r["flows"]} for r in rows]
        }
    finally:
        conn.close()


@router.get("/chain/material-flows/{country}")
def get_material_flows(
    country: str,
    flow_name: Optional[str] = Query(None, description="筛选指标: DE/DMC/IMP/EXP/PTB等"),
    category: Optional[str] = Query(None, description="筛选类别: Biomass/Fossil fuels/Metal ores等"),
    year: Optional[int] = Query(None, description="筛选年份: 1970-2019"),
    limit: int = Query(500, description="返回行数上限")
):
    """查询某国的全球物质流数据
    
    示例: /chain/material-flows/China?flow_name=DMC&year=2019
    """
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        # 检查表是否存在
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='material_flows_ts'"
        ).fetchall()
        if not tables:
            return {"status": "not_ready", "message": "物质流数据表未创建", "data": []}
        
        where = ["country = ?"]
        params = [country]
        
        if flow_name:
            where.append("flow_name = ?")
            params.append(flow_name)
        if category:
            where.append("category = ?")
            params.append(category)
        if year:
            where.append("year = ?")
            params.append(year)
        
        sql = f"SELECT country, category, flow_name, flow_unit, year, value FROM material_flows_ts WHERE {' AND '.join(where)} ORDER BY year DESC, category, flow_name LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(sql, params).fetchall()
        
        # 按 flow_name 分组统计
        flow_stats = {}
        for r in rows:
            fn = r["flow_name"]
            if fn not in flow_stats:
                flow_stats[fn] = {"min_year": 9999, "max_year": 0, "count": 0, "latest_value": 0}
            fs = flow_stats[fn]
            fs["count"] += 1
            fs["min_year"] = min(fs["min_year"], r["year"])
            fs["max_year"] = max(fs["max_year"], r["year"])
            if r["year"] >= fs.get("_latest_yr", 0):
                fs["_latest_yr"] = r["year"]
                fs["latest_value"] = r["value"]
        
        # 清理临时字段
        for v in flow_stats.values():
            v.pop("_latest_yr", None)
        
        return {
            "status": "ok",
            "country": country,
            "total": len(rows),
            "flow_summary": {k: v for k, v in sorted(flow_stats.items())},
            "data": [{
                "country": r["country"],
                "category": r["category"],
                "flow_name": r["flow_name"],
                "unit": r["flow_unit"],
                "year": r["year"],
                "value": r["value"],
            } for r in rows],
        }
    finally:
        conn.close()


@router.get("/chain/material-flows/{country}/trend")
def get_material_flow_trend(
    country: str,
    flow_name: str = Query(..., description="指标名: DE/DMC/IMP/EXP/PTB"),
    category: Optional[str] = Query(None, description="材料类别")
):
    """获取某国某指标的时间序列趋势
    
    示例: /chain/material-flows/China/trend?flow_name=DMC&category=Biomass
    """
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        where = ["country = ?", "flow_name = ?"]
        params = [country, flow_name]
        if category:
            where.append("category = ?")
            params.append(category)
        
        sql = f"SELECT year, value FROM material_flows_ts WHERE {' AND '.join(where)} ORDER BY year"
        rows = conn.execute(sql, params).fetchall()
        return {
            "country": country,
            "flow_name": flow_name,
            "category": category,
            "trend": [{"year": r["year"], "value": r["value"]} for r in rows],
        }
    finally:
        conn.close()


@router.get("/chain/stock/{symbol}/enriched")
def get_stock_supply_chain_enriched(symbol: str):
    """获取股票的完整供应链分析（含产业链路径、原材料、物质流关联）"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        bare = symbol.replace(".SH", "").replace(".SZ", "")
        company = conn.execute(
            "SELECT * FROM chain_companies WHERE code = ?", (bare,)
        ).fetchone()
        if not company:
            company = conn.execute(
                "SELECT * FROM chain_companies WHERE code LIKE ?", (f"%{bare}%",)
            ).fetchone()
        if not company:
            return {"symbol": bare, "status": "not_found"}
        
        products = conn.execute(
            "SELECT product_name, rel FROM chain_company_product WHERE company_code = ? LIMIT 20",
            (company["code"],)
        ).fetchall()
        product_names = [r["product_name"] for r in products]
        
        # 上游
        upstream_set = set()
        for pname in product_names:
            rows = conn.execute(
                "SELECT to_entity FROM chain_product_relation WHERE rel='上游材料' AND from_entity=? LIMIT 5",
                (pname,)
            ).fetchall()
            for r in rows:
                upstream_set.add(r["to_entity"])
        
        # 下游
        downstream_set = set()
        for pname in product_names:
            rows = conn.execute(
                "SELECT from_entity FROM chain_product_relation WHERE rel='下游产品' AND to_entity=? LIMIT 5",
                (pname,)
            ).fetchall()
            for r in rows:
                downstream_set.add(r["from_entity"])
        
        # 物质流关联
        try:
            material_links = conn.execute(
                "SELECT category, flow_name, year, value FROM material_flows_ts "
                "WHERE country = ? AND year >= 2018 LIMIT 20",
                ("China",)
            ).fetchall()
            material_links = [dict(r) for r in material_links]
        except Exception:
            material_links = []
        
        return {
            "symbol": bare,
            "company": dict(company),
            "products": [dict(p) for p in products],
            "upstream_materials": list(upstream_set),
            "downstream_products": list(downstream_set),
            "material_flow_links": material_links,
        }
    finally:
        conn.close()


# ===== 新闻实体匹配（纯关键词+数据库，无 LLM）=====


# ===== 新闻全局产业链图谱 =====

@router.get("/chain/news-graph")
def get_news_chain_graph(
    title: str = Query("", description="新闻标题"),
    summary: str = Query("", description="新闻摘要"),
):
    """新闻→识别主体公司→找对标(国内↔国外)→双图谱（含 edgeType）"""
    _check_chain_db()
    conn = _get_chain_conn()
    try:
        text = f"{title} {summary}".strip()
        if not text:
            return {"status": "error", "message": "需要标题或摘要", "graph_domestic": {"nodes": [], "edges": []}, "graph_foreign": {"nodes": [], "edges": []}, "bridges": []}

        text_lower = text.lower()

        # ===== 知识库：国外公司 ↔ 国内对标 =====
        FOREIGN_MAP = {
            "openai": ("United States", "人工智能", [("002230", "科大讯飞"), ("688111", "金山办公")]),
            "meta": ("United States", "互联网", [("002624", "完美世界"), ("300418", "昆仑万维")]),
            "google": ("United States", "互联网", [("002230", "科大讯飞"), ("300033", "同花顺")]),
            "microsoft": ("United States", "人工智能", [("600845", "宝信软件"), ("688111", "金山办公")]),
            "amazon": ("United States", "云计算", [("600845", "宝信软件"), ("000938", "紫光股份")]),
            "apple": ("United States", "消费电子", [("002475", "立讯精密"), ("601138", "工业富联")]),
            "nvidia": ("United States", "半导体", [("688981", "中芯国际"), ("002371", "北方华创")]),
            "tesla": ("United States", "新能源汽车", [("002594", "比亚迪"), ("300750", "宁德时代")]),
            "intel": ("United States", "半导体", [("688981", "中芯国际"), ("002371", "北方华创")]),
            "amd": ("United States", "半导体", [("688981", "中芯国际")]),
            "tsmc": ("Taiwan", "半导体", [("688981", "中芯国际")]),
            "qualcomm": ("United States", "半导体", [("000063", "中兴通讯")]),
            "oracle": ("United States", "IT服务Ⅲ", [("600845", "宝信软件")]),
            "ibm": ("United States", "IT服务Ⅲ", [("600845", "宝信软件")]),
            "nvidia": ("United States", "半导体", [("688981", "中芯国际"), ("002371", "北方华创"), ("688012", "中微公司")]),
            "boeing": ("United States", "航天卫星", [("600118", "中国卫星")]),
            "samsung": ("South Korea", "半导体", [("002049", "紫光国微")]),
            "sony": ("Japan", "消费电子", [("002475", "立讯精密")]),
            "huawei": ("China", "通信技术", [("000063", "中兴通讯")]),
            "byd": ("China", "新能源汽车", [("002594", "比亚迪")]),
            "catl": ("China", "新能源汽车", [("300750", "宁德时代")]),
        }

        CN_TOPIC_MAP = {
            "ai": ("002230", "科大讯飞"), "人工智能": ("002230", "科大讯飞"),
            "芯片": ("688981", "中芯国际"), "半导体": ("688981", "中芯国际"),
            "新能源": ("601012", "隆基绿能"), "电动车": ("002594", "比亚迪"),
            "电池": ("300750", "宁德时代"), "医药": ("600276", "恒瑞医药"),
            "医疗": ("300760", "迈瑞医疗"), "通信": ("000063", "中兴通讯"),
            "机器人": ("002747", "埃斯顿"), "汽车": ("002594", "比亚迪"),
            "消费电子": ("002475", "立讯精密"), "游戏": ("002624", "完美世界"),
            "光伏": ("601012", "隆基绿能"), "锂": ("300750", "宁德时代"),
        }

        # ===== Step 1: 判断新闻主体（纯关键词匹配）=====
        text_lc = text_lower
        foreign_entity = None
        cn_entity = None

        # 关键词匹配 FOREIGN_MAP
        for kw, (country, ind, cns) in sorted(FOREIGN_MAP.items(), key=lambda x: -len(x[0])):
            if kw in text_lc or kw in title:
                foreign_entity = (kw, country, ind, cns)
                cn_entity = cns[0]
                break

        # 关键词匹配 CN_TOPIC_MAP
        if not foreign_entity:
            for kw, (code, name) in sorted(CN_TOPIC_MAP.items(), key=lambda x: -len(x[0])):
                if kw in text_lc or kw in title:
                    cn_entity = (code, name)
                    break

        # ===== 供应链动态匹配：查询海外实体库 =====
        supply_overseas = None
        supply_relations = []
        if not foreign_entity and not cn_entity:
            # 先按单家海外实体名匹配（长词优先）
            entities = conn.execute(
                "SELECT code, name, fullname, country FROM chain_overseas_entities ORDER BY LENGTH(name) DESC"
            ).fetchall()
            for ent in entities:
                names_to_check = [ent["name"], ent["fullname"]] if ent["fullname"] else [ent["name"]]
                for n in names_to_check:
                    if n and (n in text or n.lower() in text_lc):
                        supply_overseas = [dict(ent)]
                        break
                if supply_overseas:
                    break

            # 未匹配则试 $TICKER（如 $MRVL → code MRVL）和英文名
            if not supply_overseas:
                tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
                for ent in entities:
                    ent_code = ent["code"]
                    # $TICKER 匹配
                    if ent_code in tickers:
                        supply_overseas = [dict(ent)]
                        break
                    # 英文/拼音名匹配（小写）
                    for alias in [ent_code.lower(), ent["name"].lower(), (ent["fullname"] or "").lower()]:
                        if alias and alias in text_lc:
                            supply_overseas = [dict(ent)]
                            break
                    if supply_overseas:
                        break

            # 未匹配到具体实体，再试存储/HBM行业关键词（命中则匹配三家）
            if not supply_overseas:
                storage_kws = ["hbm", "存储芯片", "闪存", "dram", "nand", "存储", "内存"]
                for skw in storage_kws:
                    if skw in text_lc:
                        rows = conn.execute(
                            "SELECT code, name, country FROM chain_overseas_entities"
                        ).fetchall()
                        if rows:
                            supply_overseas = [dict(r) for r in rows]
                        break

        # 已命中 CN_TOPIC_MAP 但文本含存储关键词时，额外跑供应链匹配
        if not supply_overseas and cn_entity and not foreign_entity:
            storage_kws = ["hbm", "存储", "存储芯片", "闪存", "dram", "nand", "内存"]
            if any(kw in text_lc for kw in storage_kws):
                rows = conn.execute(
                    "SELECT code, name, country FROM chain_overseas_entities"
                ).fetchall()
                if rows:
                    supply_overseas = [dict(r) for r in rows]

        # 数据库模糊匹配
        if not cn_entity:
            words = re.findall(r'[\u4e00-\u9fff]{2,4}', title)
            for w in words:
                row = conn.execute("SELECT code, name FROM chain_companies WHERE name LIKE ? LIMIT 1", (f'%{w}%',)).fetchone()
                if row:
                    cn_entity = (row["code"], row["name"])
                    break

        # ===== 供应链匹配：拉供应商关系 =====
        if supply_overseas and not cn_entity:
            # 以第一个海外实体的第一家供应商作为 cn_entity
            for ov in supply_overseas:
                suppliers = conn.execute("""
                    SELECT r.supplier_code, r.supplier_name, c.name as stock_name
                    FROM chain_supply_relations r
                    LEFT JOIN chain_companies c ON r.supplier_code = c.code
                    WHERE r.buyer_code = ? AND r.supplier_code IS NOT NULL
                    LIMIT 1
                """, (ov["code"],)).fetchall()
                if suppliers:
                    s = suppliers[0]
                    cn_entity = (s["supplier_code"], s["stock_name"] or s["supplier_name"])
                    break

        if supply_overseas:
            for ov in supply_overseas:
                rows = conn.execute("""
                    SELECT r.*, c.name as stock_name,
                           cat.label as category_label
                    FROM chain_supply_relations r
                    LEFT JOIN chain_companies c ON r.supplier_code = c.code
                    LEFT JOIN chain_supply_categories cat ON r.category = cat.id
                    WHERE r.buyer_code = ?
                    ORDER BY r.category, r.supplier_name
                """, (ov["code"],)).fetchall()
                supply_relations.extend([dict(r) for r in rows])

        # 无匹配 → 返回空
        if not cn_entity:
            return {"status": "ok", "title": title, "steps": [{"icon": "🔍", "label": f"新闻分析：{title[:40]}..."}, {"icon": "❌", "label": "未匹配到相关公司"}], "graph_domestic": {"nodes": [], "edges": []}, "graph_foreign": {"nodes": [], "edges": []}, "bridges": []}

        if not foreign_entity:
            if supply_overseas and len(supply_overseas) == 1:
                ov = supply_overseas[0]
                foreign_entity = (ov["name"], ov["country"], "", [cn_entity])
            else:
                foreign_entity = (None, "全球", "", [cn_entity])

        # ===== Step 2: 构建国内图谱（带 edgeType） =====
        dc_code, dc_name = cn_entity
        dn_nodes, dn_edges, dn_ids = [], [], set()

        def _add(id_, label, type_, props=None):
            if id_ not in dn_ids:
                dn_ids.add(id_)
                n = {"id": id_, "label": label, "type": type_}
                if props: n.update(props)
                dn_nodes.append(n)

        def _edge(s, t, l="", et=""):
            dn_edges.append({"source": s, "target": t, "label": l, "edgeType": et})

        _add(f"co_{dc_code}", dc_name, "company", {"main": True})
        for ind in conn.execute("SELECT DISTINCT industry_name FROM chain_company_industry WHERE company_code=?", (dc_code,)).fetchall():
            _add(f"ind_{ind['industry_name']}", ind['industry_name'], "industry")
            _edge(f"co_{dc_code}", f"ind_{ind['industry_name']}", "所属行业", "belongs_to")
        for prod in conn.execute("SELECT product_name FROM chain_company_product WHERE company_code=? LIMIT 3", (dc_code,)).fetchall():
            pname = prod["product_name"]
            _add(f"prod_{pname}", pname, "product")
            _edge(f"co_{dc_code}", f"prod_{pname}", "主营产品", "produces")
            for up in conn.execute("SELECT to_entity FROM chain_product_relation WHERE from_entity=? AND rel='上游材料' LIMIT 2", (pname,)).fetchall():
                _add(f"mat_{up['to_entity']}", up['to_entity'], "material")
                _edge(f"prod_{pname}", f"mat_{up['to_entity']}", "上游", "upstream")
            for down in conn.execute("SELECT to_entity FROM chain_product_relation WHERE from_entity=? AND rel='下游产品' LIMIT 2", (pname,)).fetchall():
                _add(f"down_{down['to_entity']}", down['to_entity'], "downstream")
                _edge(f"prod_{pname}", f"down_{down['to_entity']}", "下游", "downstream")

        # 供应链节点（海外巨头的国内供应商）
        if supply_relations:
            seen_cats = set()
            for sr in supply_relations:
                cat_label = sr["category_label"] or sr["category"]
                if cat_label not in seen_cats:
                    _add(f"supcat_{sr['category']}", cat_label, "supply_category")
                    seen_cats.add(cat_label)
                sup_id = f"sup_{sr['supplier_name']}"
                sup_label = sr["stock_name"] or sr["supplier_name"]
                if sr["supplier_code"]:
                    sup_label = f"{sup_label}({sr['supplier_code']})"
                _add(sup_id, sup_label, "supplier", {
                    "coverage": sr["coverage"],
                    "supplier_code": sr["supplier_code"] or "",
                })
                _edge(f"supcat_{sr['category']}", sup_id, sr["coverage"], "supplies")

        # ===== Step 3: 构建国外图谱 =====
        fn_name = foreign_entity[0] if foreign_entity else None
        fn_country = foreign_entity[1] if foreign_entity else "全球"
        fn_nodes, fn_edges, fn_ids = [], [], set()

        def _fn_add(id_, label, type_, props=None):
            if id_ not in fn_ids:
                fn_ids.add(id_)
                n = {"id": id_, "label": label, "type": type_}
                if props: n.update(props)
                fn_nodes.append(n)

        def _fn_edge(s, t, l="", et=""):
            fn_edges.append({"source": s, "target": t, "label": l, "edgeType": et})

        fn_label = fn_name[0].upper() + fn_name[1:] if fn_name else "全球"
        if fn_name:
            fcid = f"foreign_{fn_name.replace(' ', '_')}"
            _fn_add(fcid, fn_label, "company", {"main": True})

            cid = f"country_{fn_country.replace(' ', '_')}"
            _fn_add(cid, fn_country, "country")
            _fn_edge(fcid, cid, "总部所在地", "belongs_to")

            for r in conn.execute(
                "SELECT DISTINCT category FROM material_flows_ts WHERE country LIKE ? AND year >= 2018 LIMIT 3",
                (f"%{fn_country[:6]}%",)
            ).fetchall():
                cat = r['category']
                short = cat.replace("Fossil fuels", "石化矿产").replace("Metal ores", "金属矿产").replace("Non-metallic minerals", "工业矿产").replace("Biomass", "农林原料")
                _fn_add(f"cat_{cat}", short, "industry")
                _fn_edge(fcid, f"cat_{cat}", "进出口", "belongs_to")

        # 多海外实体节点（供应链匹配到多家时）
        if supply_overseas and len(supply_overseas) > 1:
            for ov in supply_overseas:
                _fn_add(f"foreign_{ov['name'].replace(' ', '_')}", ov["name"], "company", {"main": True})
                _fn_add(f"cntry_{ov['country'].replace(' ', '_')}", ov["country"], "country")
                _fn_edge(
                    f"foreign_{ov['name'].replace(' ', '_')}",
                    f"cntry_{ov['country'].replace(' ', '_')}",
                    "总部所在地", "belongs_to",
                )

        # ===== Step 4: 桥梁边 =====
        bridges = []
        if fn_name:
            for ind in conn.execute(
                "SELECT DISTINCT industry_name FROM chain_company_industry WHERE company_code=?", (dc_code,)
            ).fetchall():
                for cat_r in conn.execute(
                    "SELECT DISTINCT category FROM material_flows_ts WHERE country LIKE ? AND year>=2018 LIMIT 2",
                    (f"%{fn_country[:6]}%",)
                ).fetchall():
                    bridges.append({
                        "source": f"ind_{ind['industry_name']}", "source_type": "industry",
                        "target": f"cat_{cat_r['category']}", "target_type": "category",
                        "label": "跨境供应链", "edgeType": "bridge",
                    })

            if not bridges:
                bridges.append({
                    "source": f"co_{dc_code}", "source_type": "company",
                    "target": fcid, "target_type": "company",
                    "label": "对标关系", "edgeType": "foreign_peer",
                })

        # 供应链桥梁（海外巨头 → 国内供应商品类）
        if supply_overseas and supply_relations:
            seen_cat_bridges = set()
            for ov in supply_overseas:
                ov_id = f"foreign_{ov['name'].replace(' ', '_')}"
                for sr in supply_relations:
                    cat_key = sr["category"]
                    if cat_key not in seen_cat_bridges:
                        seen_cat_bridges.add(cat_key)
                        bridges.append({
                            "source": f"supcat_{cat_key}", "source_type": "supply_category",
                            "target": ov_id, "target_type": "overseas",
                            "label": f"供应 {ov['name']}", "edgeType": "supply_chain",
                        })

        # ===== Step 5: 组装 =====
        steps = []
        steps.append({"icon": "🔍", "label": f"新闻分析：{title[:40]}..."})
        steps.append({"icon": "🏢", "label": f"识别：{dc_name} ({dc_code})" + (f" → 对标 {fn_label}" if foreign_entity and foreign_entity[0] else "")})
        if fn_name:
            steps.append({"icon": "🌐", "label": f"国外对标：{fn_label} ({fn_country})"})
        if supply_relations:
            cat_count = len(set(sr["category"] for sr in supply_relations))
            sup_count = len(set(sr["supplier_name"] for sr in supply_relations))
            steps.append({"icon": "🔗", "label": f"供应链：{sup_count} 家供应商 · {cat_count} 个品类"})
        steps.append({"icon": "🗺️", "label": f"生成图谱：国内 {len(dn_nodes)} 节点 · 全球 {len(fn_nodes)} 节点"})

        return {
            "status": "ok",
            "title": title,
            "main_domestic": {"code": dc_code, "name": dc_name},
            "main_foreign": {"name": fn_label, "country": fn_country},
            "steps": steps,
            "graph_domestic": {"nodes": dn_nodes, "edges": dn_edges},
            "graph_foreign": {"nodes": fn_nodes, "edges": fn_edges},
            "bridges": bridges,
        }
    finally:
        conn.close()


# ===== 新闻供应链分析（纯关键词匹配，无 LLM）=====

@router.get("/chain/news-supply-chain")
def get_news_supply_chain(
    title: str = Query("", description="新闻标题"),
    summary: str = Query("", description="新闻摘要"),
):
    """新闻 → 关键词匹配公司 → 双图谱（国内/国外）"""
    if not title and not summary:
        return {"status": "error", "message": "需要标题或摘要", "graph_domestic": {"nodes": [], "edges": []}, "graph_foreign": {"nodes": [], "edges": []}, "bridges": []}

    # 复用 news-graph 的逻辑寻找主体公司
    text = f"{title} {summary}".strip()
    text_lc = text.lower()

    FOREIGN_MAP = {
        "openai": ("United States", "人工智能", [("002230", "科大讯飞"), ("688111", "金山办公")]),
        "meta": ("United States", "互联网", [("002624", "完美世界"), ("300418", "昆仑万维")]),
        "google": ("United States", "互联网", [("002230", "科大讯飞"), ("300033", "同花顺")]),
        "microsoft": ("United States", "人工智能", [("600845", "宝信软件"), ("688111", "金山办公")]),
        "amazon": ("United States", "云计算", [("600845", "宝信软件"), ("000938", "紫光股份")]),
        "apple": ("United States", "消费电子", [("002475", "立讯精密"), ("601138", "工业富联")]),
        "nvidia": ("United States", "半导体", [("688981", "中芯国际"), ("002371", "北方华创")]),
        "tesla": ("United States", "新能源汽车", [("002594", "比亚迪"), ("300750", "宁德时代")]),
        "intel": ("United States", "半导体", [("688981", "中芯国际"), ("002371", "北方华创")]),
        "amd": ("United States", "半导体", [("688981", "中芯国际")]),
        "tsmc": ("Taiwan", "半导体", [("688981", "中芯国际")]),
        "qualcomm": ("United States", "半导体", [("000063", "中兴通讯")]),
        "huawei": ("China", "通信技术", [("000063", "中兴通讯")]),
    }
    CN_TOPIC_MAP = {
        "ai": ("002230", "科大讯飞"), "人工智能": ("002230", "科大讯飞"),
        "芯片": ("688981", "中芯国际"), "半导体": ("688981", "中芯国际"),
        "新能源": ("601012", "隆基绿能"), "电动车": ("002594", "比亚迪"),
        "电池": ("300750", "宁德时代"), "医药": ("600276", "恒瑞医药"),
        "机器人": ("002747", "埃斯顿"), "汽车": ("002594", "比亚迪"),
    }

    foreign_entity = None
    cn_entity = None
    for kw, (country, ind, cns) in sorted(FOREIGN_MAP.items(), key=lambda x: -len(x[0])):
        if kw in text_lc or kw in title:
            foreign_entity = (kw, country, ind, cns)
            cn_entity = cns[0]
            break
    if not cn_entity:
        for kw, (code, name) in sorted(CN_TOPIC_MAP.items(), key=lambda x: -len(x[0])):
            if kw in text_lc or kw in title:
                cn_entity = (code, name)
                break
    # 查海外实体表（中文名匹配 — 支持简称如"海力士"→"SK海力士"）
    overseas_code = None
    if not foreign_entity:
        try:
            conn = _get_chain_conn()
            for oe in conn.execute("SELECT code, name, fullname FROM chain_overseas_entities").fetchall():
                oe_name = oe["name"]
                oe_code = oe["code"]
                oe_fullname = oe["fullname"] or ""
                # 精确含中文名/英文名
                if oe_name in title or oe_name in text_lc or oe_fullname in title or oe_fullname in text_lc:
                    overseas_code = oe_code
                    break
                # 中文名拆词：SK海力士 → 匹配"海力士"
                for part in re.findall(r'[\u4e00-\u9fff]{2,}', oe_name):
                    if part in title or part in text_lc:
                        overseas_code = oe["code"]
                        break
                if overseas_code:
                    break
                # 英文/拼音名匹配 + $TICKER 匹配
                # 1) 硬编码别名（兼容旧数据）
                aliases = {"SAMSUNG": ["samsung", "삼성"], "SK_HYNIX": ["sk hynix", "hynix", "하이닉스"], "MICRON": ["micron", "마이크론"]}
                for alias in aliases.get(oe["code"], []):
                    if alias in text_lc:
                        overseas_code = oe["code"]
                        break
                if overseas_code:
                    break
                # 2) 通用英文名匹配（code 小写、name 英文、fullname 英文）
                for alias in [oe["code"].lower(), (oe["name"] or "").lower()]:
                    if alias and len(alias) > 1 and alias in text_lc:
                        overseas_code = oe["code"]
                        break
                if overseas_code:
                    break
                # 3) $TICKER 匹配（如 $MRVL → MRVL）
                tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
                if oe["code"] in tickers:
                    overseas_code = oe["code"]
                    break
            conn.close()
        except:
            pass

    # 关键词触发：存储/HBM/内存 → 同时查三家海外巨头
    _storage_kws = ["存储", "hbm", "内存", "dram", "nand", "闪存"]
    if not overseas_code:
        for kw in _storage_kws:
            if kw in title.lower() or kw in text_lc:
                # 返回所有海外实体的供应链
                overseas_code = "__ALL__"
                break

    if overseas_code:
        # === 海外实体供应链模式 ===
        conn = _get_chain_conn()
        try:
            is_all = (overseas_code == "__ALL__")

            # 查询海外实体信息
            if is_all:
                overseas_list = conn.execute("SELECT code, name FROM chain_overseas_entities").fetchall()
                # 查所有海外实体的供应链
                placeholders = ",".join("?" * len(overseas_list))
                codes = [r["code"] for r in overseas_list]
                rows = conn.execute(f"""
                    SELECT r.buyer_code, r.category, c.label as cat_label, r.supplier_code, r.supplier_name, r.notes
                    FROM chain_supply_relations r
                    LEFT JOIN chain_supply_categories c ON r.category = c.id
                    WHERE r.buyer_code IN ({placeholders})
                    ORDER BY r.buyer_code, r.category, r.supplier_code
                """, codes).fetchall()
                oe_name = f"{len(overseas_list)}家海外巨头"
            else:
                oe = conn.execute("SELECT code, name FROM chain_overseas_entities WHERE code=?", (overseas_code,)).fetchone()
                if not oe:
                    raise ValueError("海外实体未找到")
                oe_name = oe["name"]
                rows = conn.execute("""
                    SELECT r.buyer_code, r.category, c.label as cat_label, r.supplier_code, r.supplier_name, r.notes
                    FROM chain_supply_relations r
                    LEFT JOIN chain_supply_categories c ON r.category = c.id
                    WHERE r.buyer_code = ?
                    ORDER BY r.category, r.supplier_code
                """, (overseas_code,)).fetchall()

            # 构建国内供应商图谱（按品类分组）
            dn_nodes, dn_edges, dn_ids = [], [], set()
            cats = set()

            def _add(nid, label, ntype, main=False):
                if nid not in dn_ids:
                    dn_ids.add(nid)
                    dn_nodes.append({"id": nid, "label": label, "type": ntype, "main": main})

            def _edge(s, t, label="", et=""):
                if not any(e["source"] == s and e["target"] == t for e in dn_edges):
                    dn_edges.append({"source": s, "target": t, "label": label, "edgeType": et})

            # 品类节点 + 供应商节点
            for r in rows:
                if r["cat_label"] and r["category"] not in cats:
                    cats.add(r["category"])
                    _add(f"cat_{r['category']}", r["cat_label"], "category")
                _add(f"co_{r['supplier_code']}", r["supplier_name"] or r["supplier_code"], "company")
                _edge(f"co_{r['supplier_code']}", f"cat_{r['category']}", "所属品类", "belongs_to")

            # 海外图谱
            fn_nodes, fn_ids = [], set()
            def _fn(nid, label, ntype):
                if nid not in fn_ids:
                    fn_ids.add(nid)
                    fn_nodes.append({"id": nid, "label": label, "type": ntype})

            if is_all:
                for oe_entity in overseas_list:
                    _fn(f"foreign_{oe_entity['code']}", oe_entity["name"], "company")
            else:
                _fn(f"foreign_{overseas_code}", oe_name, "company")

            # 桥梁：品类 → 海外实体
            bridges = []
            if is_all:
                # 每个品类连接到所有海外实体
                for cid in cats:
                    for oe_entity in overseas_list:
                        bridges.append({
                            "source": f"cat_{cid}", "source_type": "category",
                            "target": f"foreign_{oe_entity['code']}", "target_type": "company",
                            "label": "供应", "edgeType": "supply",
                        })
            else:
                for cid in cats:
                    bridges.append({
                        "source": f"cat_{cid}", "source_type": "category",
                        "target": f"foreign_{overseas_code}", "target_type": "company",
                        "label": "供应", "edgeType": "supply",
                    })

            supplier_count = len(set(r["supplier_code"] for r in rows))
            steps = [
                {"icon": "🔍", "label": f"新闻分析：{title[:40]}..."},
                {"icon": "🌐", "label": f"识别海外实体：{oe_name}"},
                {"icon": "🔗", "label": f"查询到 {supplier_count} 家供应商，{len(cats)} 个品类"},
            ]

            return {
                "status": "ok",
                "title": title,
                "mode": "supply_chain",
                "main_domestic": {"name": f"{supplier_count}家供应商"},
                "main_foreign": {"name": oe_name},
                "steps": steps,
                "graph_domestic": {"nodes": dn_nodes, "edges": dn_edges},
                "graph_foreign": {"nodes": fn_nodes, "edges": []},
                "bridges": bridges,
            }
        finally:
            conn.close()

    # 未匹配海外实体 → 原有逻辑（关键词映射/公司匹配）
    if not cn_entity:
        try:
            conn = _get_chain_conn()
            words = re.findall(r'[\u4e00-\u9fff]{2,4}', title)
            for w in words:
                row = conn.execute("SELECT code, name FROM chain_companies WHERE name LIKE ? LIMIT 1", (f'%{w}%',)).fetchone()
                if row:
                    cn_entity = (row["code"], row["name"])
                    break
            conn.close()
        except:
            pass
    if not cn_entity:
        return {"status": "ok", "title": title, "mode": "supply_chain", "main_domestic": {"name": ""}, "main_foreign": {"name": "全球"}, "steps": [{"icon": "🔍", "label": f"新闻分析：{title[:40]}..."}, {"icon": "❌", "label": "未匹配到相关公司"}], "graph_domestic": {"nodes": [], "edges": []}, "graph_foreign": {"nodes": [], "edges": []}, "bridges": []}

    dc_code, dc_name = cn_entity
    dn_nodes, dn_edges, dn_ids = [], [], set()

    def add_dom(nid, label, ntype, main=False):
        if nid not in dn_ids:
            dn_ids.add(nid)
            dn_nodes.append({"id": nid, "label": label, "type": ntype, "main": main})

    def add_dom_edge(s, t, label="", et=""):
        if not any(e["source"] == s and e["target"] == t for e in dn_edges):
            dn_edges.append({"source": s, "target": t, "label": label, "edgeType": et})

    add_dom(f"co_{dc_code}", dc_name, "company", main=True)

    # 查询数据库补充行业、产品、上下游信息
    try:
        conn = _get_chain_conn()
        for ind in conn.execute("SELECT DISTINCT industry_name FROM chain_company_industry WHERE company_code=?", (dc_code,)).fetchall():
            add_dom(f"ind_{ind['industry_name']}", ind['industry_name'], "industry")
            add_dom_edge(f"co_{dc_code}", f"ind_{ind['industry_name']}", "所属行业", "belongs_to")
        for prod in conn.execute("SELECT product_name FROM chain_company_product WHERE company_code=? LIMIT 3", (dc_code,)).fetchall():
            pname = prod["product_name"]
            add_dom(f"prod_{pname}", pname, "product")
            add_dom_edge(f"co_{dc_code}", f"prod_{pname}", "主营产品", "produces")
            for up in conn.execute("SELECT to_entity FROM chain_product_relation WHERE from_entity=? AND rel='上游材料' LIMIT 2", (pname,)).fetchall():
                add_dom(f"mat_{up['to_entity']}", up['to_entity'], "material")
                add_dom_edge(f"prod_{pname}", f"mat_{up['to_entity']}", "上游", "upstream")
            for down in conn.execute("SELECT to_entity FROM chain_product_relation WHERE from_entity=? AND rel='下游产品' LIMIT 2", (pname,)).fetchall():
                add_dom(f"down_{down['to_entity']}", down['to_entity'], "downstream")
                add_dom_edge(f"prod_{pname}", f"down_{down['to_entity']}", "下游", "downstream")
        conn.close()
    except:
        pass

    # 国外图谱
    fn_nodes, fn_edges, fn_ids = [], [], set()
    def add_fn(nid, label, ntype):
        if nid not in fn_ids:
            fn_ids.add(nid)
            fn_nodes.append({"id": nid, "label": label, "type": ntype})

    if foreign_entity:
        fn_label = foreign_entity[0][0].upper() + foreign_entity[0][1:]
        add_fn(f"foreign_{foreign_entity[0].replace(' ', '_')}", fn_label, "company")
        add_fn(f"country_{foreign_entity[1].replace(' ', '_')}", foreign_entity[1], "country")
    add_fn("foreign_market", "海外市场", "industry")

    bridges = []
    for fn in fn_nodes:
        bridges.append({
            "source": f"co_{dc_code}", "source_type": "company",
            "target": fn["id"], "target_type": "company",
            "label": "跨境对标", "edgeType": "foreign_peer",
        })

    steps = [
        {"icon": "🔍", "label": f"新闻分析：{title[:40]}..."},
        {"icon": "🏢", "label": f"识别到：{dc_name} ({dc_code})"},
        {"icon": "🗺️", "label": f"生成图谱：国内 {len(dn_nodes)} 节点 · 全球 {len(fn_nodes)} 节点"},
    ]

    return {
        "status": "ok",
        "title": title,
        "mode": "supply_chain",
        "main_domestic": {"name": dc_name},
        "main_foreign": {"name": foreign_entity[0].capitalize() if foreign_entity else "全球"},
        "steps": steps,
        "graph_domestic": {"nodes": dn_nodes, "edges": dn_edges},
        "graph_foreign": {"nodes": fn_nodes, "edges": fn_edges},
        "bridges": bridges,
    }


# ===== 智能展开（双击企业节点调用 Ollama 分析上下游）=====

_chain_db_path = str(_main_db)


@router.get("/chain/expand-smart")
def expand_smart(code: str = Query(...), name: str = Query("")):
    """双击图谱公司节点：查供应链DB + Ollama分析 → 返回图数据"""
    conn = sqlite3.connect(_chain_db_path)
    conn.row_factory = sqlite3.Row
    try:
        company = conn.execute("SELECT * FROM chain_companies WHERE code=?", (code,)).fetchone()
        if not company:
            company = conn.execute("SELECT * FROM chain_companies WHERE code LIKE ?", (f"%{code}%",)).fetchone()
        if not company:
            return {"status": "error", "message": f"未找到 {code}", "graph": {"nodes": [], "edges": []}}

        cname, ccode = company["name"], company["code"]
        code6 = ccode[:6]

        products = conn.execute("SELECT product_name FROM chain_company_product WHERE company_code=? LIMIT 5", (code6,)).fetchall()
        product_names = [r["product_name"] for r in products]
        industries = conn.execute("SELECT industry_name FROM chain_company_industry WHERE company_code=?", (code6,)).fetchall()
        industry_names = [r["industry_name"] for r in industries]

        upstream_materials = []
        for pname in product_names:
            for r in conn.execute("SELECT to_entity FROM chain_product_relation WHERE from_entity=? AND rel='上游材料' LIMIT 3", (pname,)).fetchall():
                upstream_materials.append({"product": pname, "material": r["to_entity"]})

        downstream_products = []
        for pname in product_names:
            for r in conn.execute("SELECT DISTINCT from_entity FROM chain_product_relation WHERE to_entity=? AND rel='下游产品' LIMIT 3", (pname,)).fetchall():
                downstream_products.append({"product": r["from_entity"], "uses": pname})

        peers = []
        try:
            peers = conn.execute("SELECT peer_code, peer_name FROM chain_same_industry WHERE company_code=? LIMIT 10", (code6,)).fetchall()
        except Exception:
            peers = []
        same_product_companies = []
        for pname in product_names[:2]:
            for r in conn.execute("SELECT company_code, company_name FROM chain_company_product WHERE product_name=? AND company_code!=? LIMIT 5", (pname, code6)).fetchall():
                same_product_companies.append({"code": r["company_code"], "name": r["company_name"]})

        # 构建图（带 edgeType）
        analysis_text = {}
        nodes, edges = [], []
        nids, eids = set(), set()

        def add_node(nid, label, ntype, main=False):
            if nid not in nids:
                nids.add(nid)
                nodes.append({"id": nid, "label": label, "type": ntype, "main": main})

        def add_edge(s, t, label="", edge_type=""):
            ek = f"{s}→{t}"
            if ek not in eids:
                eids.add(ek)
                edges.append({"source": s, "target": t, "label": label, "edgeType": edge_type})

        add_node(f"co_{ccode}", cname, "company", main=True)
        for ind in industry_names:
            add_node(f"ind_{ind}", ind, "industry")
            add_edge(f"co_{ccode}", f"ind_{ind}", "所属行业", "belongs_to")
        for pname in product_names:
            add_node(f"prod_{pname}", pname, "product")
            add_edge(f"co_{ccode}", f"prod_{pname}", "主营产品", "produces")
        for um in upstream_materials:
            add_node(f"mat_{um['material']}", um["material"], "material")
            add_edge(f"prod_{um['product']}", f"mat_{um['material']}", "上游原材料", "upstream")
        for dp in downstream_products:
            add_node(f"down_{dp['product']}", dp["product"], "downstream")
            add_edge(f"down_{dp['product']}", f"prod_{dp['uses']}", "下游使用", "downstream")
        for peer in peers:
            add_node(f"co_{peer['peer_code']}", peer["peer_name"], "company")
            add_edge(f"co_{ccode}", f"co_{peer['peer_code']}", "同业竞争", "competitor")
        for sc in same_product_companies:
            add_node(f"co_{sc['code']}", sc["name"], "company")
            add_edge(f"co_{ccode}", f"co_{sc['code']}", "同类产品", "competitor")

        return {
            "status": "ok", "code": ccode, "name": cname,
            "analysis": analysis_text,
            "graph": {"nodes": nodes, "edges": edges},
            "stats": {"products": len(product_names), "upstream": len(upstream_materials),
                      "downstream": len(downstream_products), "peers": len(peers)},
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"status": "error", "message": str(e), "graph": {"nodes": [], "edges": []}}
    finally:
        conn.close()


# ===== 新闻分析异步队列（Hermes supply-chain-analyst skill 处理）=====

import uuid as _uuid

def _init_news_queue():
    """初始化 news_analysis_queue 表"""
    db = _main_db
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_analysis_queue (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            result TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()

_init_news_queue()


@router.post("/chain/news-request")
def submit_news_analysis(body: dict):
    """提交新闻分析请求 → 返回 task_id，Hermes 异步处理"""
    title = (body or {}).get("title", "")
    summary = (body or {}).get("summary", "")
    if not title:
        return {"status": "error", "message": "需要标题"}

    task_id = str(_uuid.uuid4())[:8]
    conn = sqlite3.connect(str(_main_db))
    conn.execute(
        "INSERT INTO news_analysis_queue (id, title, summary, status) VALUES (?, ?, ?, 'pending')",
        (task_id, title, summary),
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, "status": "pending"}


@router.get("/chain/news-request/{task_id}")
def get_news_analysis_result(task_id: str):
    """查询新闻分析结果"""
    conn = sqlite3.connect(str(_main_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, title, status, result, created_at, updated_at FROM news_analysis_queue WHERE id=?",
        (task_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {"status": "error", "message": "任务不存在"}
    result = {
        "status": row["status"],
        "task_id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if row["result"]:
        try:
            result["result"] = json.loads(row["result"])
        except:
            result["result"] = row["result"]
    return result


@router.get("/chain/news-queue-pending")
def list_pending_requests(limit: int = 10):
    """列出待处理的分析请求（给 Hermes cron job 用）"""
    conn = sqlite3.connect(str(_main_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, summary, created_at FROM news_analysis_queue WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {
        "pending": [
            {"task_id": r["id"], "title": r["title"], "summary": r["summary"], "created_at": r["created_at"]}
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/chain/news-queue-update")
def update_news_result(body: dict):
    """更新分析结果（给 Hermes cron job 调用）"""
    task_id = (body or {}).get("task_id", "")
    result_json = (body or {}).get("result", {})
    status = (body or {}).get("status", "done")
    if not task_id:
        return {"status": "error", "message": "需要 task_id"}

    conn = sqlite3.connect(str(_main_db))
    conn.execute(
        "UPDATE news_analysis_queue SET status=?, result=?, updated_at=datetime('now','localtime') WHERE id=?",
        (status, json.dumps(result_json, ensure_ascii=False), task_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}
