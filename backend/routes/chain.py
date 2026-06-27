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
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/v1", tags=["产业链"])

# 数据库路径
_chain_db = Path(__file__).resolve().parent.parent.parent / "data" / "chain.db"
_main_db = Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")


def _get_chain_conn():
    """获取产业链数据库连接"""
    conn = sqlite3.connect(str(_chain_db))
    conn.row_factory = sqlite3.Row
    return conn


def _check_chain_db():
    """检查产业链数据库是否已导入"""
    if not _chain_db.exists():
        raise HTTPException(503, detail="产业链数据库未就绪，请先运行 chain_import")
    return str(_chain_db)


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
