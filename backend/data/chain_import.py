"""
ChainKnowledgeGraph 数据导入 SQLite

将 ChainKnowledgeGraph 的 7 个 JSONL 文件导入 SQLite，建立索引支持快速产业链查询。
数据格式: 每行一个 JSON 对象（JSONL），非 JSON 数组。

表结构:
  - chain_companies:   上市公司 (code, name, fullname, location, list_time)
  - chain_industries:  行业分类 (code, name)
  - chain_products:    产品实体 (name, ...)
  - chain_company_industry: 公司-行业关系
  - chain_industry_tree:    行业-行业上下级
  - chain_product_relation: 产品-产品上下游/小类
  - chain_company_product:  公司-主营产品
"""
import json
import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime

# 数据目录
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chain_knowledge"
DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"


def _normalize_code(code: str) -> str:
    """将 600373.SH → 600373，保留纯数字代码"""
    return code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").strip()


def import_all(db_path: str = ""):
    """导入所有 ChainKnowledgeGraph 数据到 SQLite"""
    if not db_path:
        db_path = str(DB_PATH)
    
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    
    # ===== 建表 =====
    conn.executescript("""
        DROP TABLE IF EXISTS chain_companies;
        CREATE TABLE chain_companies (
            code        TEXT PRIMARY KEY,   -- 6位数字代码
            name        TEXT,
            fullname    TEXT,
            location    TEXT,               -- 深圳证券交易所/上海证券交易所
            list_time   TEXT                -- 上市日期
        );
        CREATE INDEX idx_chain_companies_name ON chain_companies(name);
        
        DROP TABLE IF EXISTS chain_industries;
        CREATE TABLE chain_industries (
            code        TEXT PRIMARY KEY,   -- 申万行业代码，6位
            name        TEXT
        );
        CREATE INDEX idx_chain_industries_name ON chain_industries(name);
        
        DROP TABLE IF EXISTS chain_company_industry;
        CREATE TABLE chain_company_industry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            company_name TEXT,
            industry_code TEXT,
            industry_name TEXT,
            rel         TEXT DEFAULT '所属行业'
        );
        CREATE INDEX idx_cci_company ON chain_company_industry(company_code);
        CREATE INDEX idx_cci_industry ON chain_company_industry(industry_code);
        CREATE INDEX idx_cci_industry_name ON chain_company_industry(industry_name);
        
        DROP TABLE IF EXISTS chain_industry_tree;
        CREATE TABLE chain_industry_tree (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            from_code       TEXT,
            from_industry   TEXT,
            to_code         TEXT,
            to_industry     TEXT,
            rel             TEXT DEFAULT '上级行业'
        );
        CREATE INDEX idx_cit_from ON chain_industry_tree(from_code);
        CREATE INDEX idx_cit_to ON chain_industry_tree(to_code);
        
        DROP TABLE IF EXISTS chain_product_relation;
        CREATE TABLE chain_product_relation (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            from_entity TEXT,
            to_entity   TEXT,
            rel         TEXT    -- 上游材料 / 下游产品 / 产品小类
        );
        CREATE INDEX idx_cpr_from ON chain_product_relation(from_entity);
        CREATE INDEX idx_cpr_to ON chain_product_relation(to_entity);
        CREATE INDEX idx_cpr_rel ON chain_product_relation(rel);
        
        DROP TABLE IF EXISTS chain_company_product;
        CREATE TABLE chain_company_product (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code    TEXT,
            company_name    TEXT,
            product_name    TEXT,
            rel             TEXT
        );
        CREATE INDEX idx_ccp_company ON chain_company_product(company_code);
        CREATE INDEX idx_ccp_product ON chain_company_product(product_name);
        
        -- 元数据表
        DROP TABLE IF EXISTS chain_meta;
        CREATE TABLE chain_meta (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );
    """)
    
    # ===== 导入 company.json =====
    count = 0
    fpath = DATA_DIR / "company.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append((
                        obj.get("code", ""),
                        obj.get("name", ""),
                        obj.get("fullname", ""),
                        obj.get("location", ""),
                        obj.get("time", ""),
                    ))
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 5000:
                    conn.executemany(
                        "INSERT OR REPLACE INTO chain_companies VALUES (?,?,?,?,?)",
                        rows
                    )
                    count += len(rows)
                    rows = []
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO chain_companies VALUES (?,?,?,?,?)",
                    rows
                )
                count += len(rows)
        print(f"[chain_import] companies: {count} rows")
    
    # ===== 导入 industry.json =====
    count = 0
    fpath = DATA_DIR / "industry.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append((obj.get("code", ""), obj.get("name", "")))
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 5000:
                    conn.executemany("INSERT OR REPLACE INTO chain_industries VALUES (?,?)", rows)
                    count += len(rows)
                    rows = []
            if rows:
                conn.executemany("INSERT OR REPLACE INTO chain_industries VALUES (?,?)", rows)
                count += len(rows)
        print(f"[chain_import] industries: {count} rows")
    
    # ===== 导入 company_industry.json =====
    count = 0
    fpath = DATA_DIR / "company_industry.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append((
                        _normalize_code(obj.get("company_code", "")),
                        obj.get("company_name", ""),
                        obj.get("industry_code", ""),
                        obj.get("industry_name", ""),
                        obj.get("rel", "所属行业"),
                    ))
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 5000:
                    conn.executemany(
                        "INSERT INTO chain_company_industry (company_code,company_name,industry_code,industry_name,rel) VALUES (?,?,?,?,?)",
                        rows
                    )
                    count += len(rows)
                    rows = []
            if rows:
                conn.executemany(
                    "INSERT INTO chain_company_industry (company_code,company_name,industry_code,industry_name,rel) VALUES (?,?,?,?,?)",
                    rows
                )
                count += len(rows)
        print(f"[chain_import] company_industry: {count} rows")
    
    # ===== 导入 industry_industry.json =====
    count = 0
    fpath = DATA_DIR / "industry_industry.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append((
                        obj.get("from_code", ""),
                        obj.get("from_industry", ""),
                        obj.get("to_code", ""),
                        obj.get("to_industry", ""),
                        obj.get("rel", "上级行业"),
                    ))
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 5000:
                    conn.executemany(
                        "INSERT INTO chain_industry_tree (from_code,from_industry,to_code,to_industry,rel) VALUES (?,?,?,?,?)",
                        rows
                    )
                    count += len(rows)
                    rows = []
            if rows:
                conn.executemany(
                    "INSERT INTO chain_industry_tree (from_code,from_industry,to_code,to_industry,rel) VALUES (?,?,?,?,?)",
                    rows
                )
                count += len(rows)
        print(f"[chain_import] industry_tree: {count} rows")
    
    # ===== 导入 product_product.json =====
    count_upstream = 0
    count_downstream = 0
    count_sub = 0
    fpath = DATA_DIR / "product_product.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rel = obj.get("rel", "")
                    rows.append((
                        obj.get("from_entity", ""),
                        obj.get("to_entity", ""),
                        rel,
                    ))
                    if rel == "上游材料":
                        count_upstream += 1
                    elif rel == "下游产品":
                        count_downstream += 1
                    else:
                        count_sub += 1
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 10000:
                    conn.executemany(
                        "INSERT INTO chain_product_relation (from_entity,to_entity,rel) VALUES (?,?,?)",
                        rows
                    )
                    rows = []
            if rows:
                conn.executemany(
                    "INSERT INTO chain_product_relation (from_entity,to_entity,rel) VALUES (?,?,?)",
                    rows
                )
        print(f"[chain_import] product_relations: upstream={count_upstream}, downstream={count_downstream}, subtype={count_sub}")
    
    # ===== 导入 company_product.json =====
    count = 0
    fpath = DATA_DIR / "company_product.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append((
                        _normalize_code(obj.get("company_code", "")),
                        obj.get("company_name", ""),
                        obj.get("product_name", obj.get("product", "")),
                        obj.get("rel", "主营产品"),
                    ))
                except json.JSONDecodeError:
                    pass
                if len(rows) >= 5000:
                    conn.executemany(
                        "INSERT INTO chain_company_product (company_code,company_name,product_name,rel) VALUES (?,?,?,?)",
                        rows
                    )
                    count += len(rows)
                    rows = []
            if rows:
                conn.executemany(
                    "INSERT INTO chain_company_product (company_code,company_name,product_name,rel) VALUES (?,?,?,?)",
                    rows
                )
                count += len(rows)
        print(f"[chain_import] company_product: {count} rows")
    
    # ===== 写入元数据 =====
    conn.execute(
        "INSERT OR REPLACE INTO chain_meta VALUES (?,?)",
        ("import_time", datetime.now().isoformat())
    )
    
    # ===== 建立辅助视图（物化查询加速） =====
    conn.executescript("""
        -- 公司完整产业链视图：公司 → 产品 → 上游原材料
        DROP VIEW IF EXISTS chain_company_upstream;
        CREATE VIEW chain_company_upstream AS
        SELECT DISTINCT
            ccp.company_code,
            ccp.company_name,
            ccp.product_name AS own_product,
            cpr_up.to_entity AS upstream_material,
            cpr_down.from_entity AS made_from -- 使用该材料做成的产品（验证链路）
        FROM chain_company_product ccp
        JOIN chain_product_relation cpr_down ON ccp.product_name = cpr_down.from_entity AND cpr_down.rel = '上游材料'
        LEFT JOIN chain_product_relation cpr_up ON cpr_down.to_entity = cpr_up.from_entity AND cpr_up.rel = '产品小类'
        WHERE cpr_down.to_entity IS NOT NULL;
        
        -- 公司产品下游关系
        DROP VIEW IF EXISTS chain_company_downstream;
        CREATE VIEW chain_company_downstream AS
        SELECT DISTINCT
            ccp.company_code,
            ccp.company_name,
            ccp.product_name,
            cpr.to_entity AS downstream_product
        FROM chain_company_product ccp
        JOIN chain_product_relation cpr ON ccp.product_name = cpr.from_entity AND cpr.rel = '下游产品';
        
        -- 同行业公司
        DROP VIEW IF EXISTS chain_same_industry;
        CREATE VIEW chain_same_industry AS
        SELECT 
            ci1.company_code AS company_code,
            ci1.company_name AS company_name,
            ci1.industry_name,
            ci2.company_code AS peer_code,
            ci2.company_name AS peer_name
        FROM chain_company_industry ci1
        JOIN chain_company_industry ci2 
            ON ci1.industry_code = ci2.industry_code 
            AND ci1.company_code != ci2.company_code;
    """)
    
    conn.commit()
    conn.close()
    
    # 打印统计
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"\n[chain_import] ✅ 导入完成，数据库: {db_path} ({db_size_mb:.1f} MB)")


if __name__ == "__main__":
    import_all()
