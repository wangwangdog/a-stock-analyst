"""
功率芯片上市公司入库脚本
狗哥 2026-06-29 提供数据
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

# 功率芯片公司数据 (狗哥提供)
COMPANIES = [
    # (代码, 简称, 全称, 上市地, 赛道路径)
    # (一) IDM一体化龙头
    ("600460", "士兰微", "杭州士兰微电子股份有限公司", "上海证券交易所", "功率半导体 → IDM一体化 → IGBT/MOSFET/碳化硅"),
    ("688396", "华润微", "华润微电子有限公司", "上海证券交易所", "功率半导体 → IDM一体化 → MOSFET/12英寸功率晶圆"),
    ("600745", "闻泰科技", "闻泰科技股份有限公司", "上海证券交易所", "功率半导体 → IDM一体化 → 车规MOS/二极管/功率模组"),
    ("300373", "扬杰科技", "扬州扬杰电子科技股份有限公司", "深圳证券交易所", "功率半导体 → 分立器件 → 二极管/整流桥/SiC"),
    ("600360", "华微电子", "吉林华微电子股份有限公司", "上海证券交易所", "功率半导体 → IDM一体化 → 晶闸管/中高压MOS"),
    # (二) IGBT模块专精
    ("603290", "斯达半导", "嘉兴斯达半导体股份有限公司", "上海证券交易所", "功率半导体 → IGBT模块 → 车规IGBT/SiC模块"),
    ("688711", "宏微科技", "江苏宏微科技股份有限公司", "上海证券交易所", "功率半导体 → IGBT模块 → IGBT/快恢复二极管"),
    ("300046", "台基股份", "湖北台基半导体股份有限公司", "深圳证券交易所", "功率半导体 → IGBT模块 → 晶闸管/IGBT模块"),
    # (三) MOSFET设计
    ("605111", "新洁能", "无锡新洁能股份有限公司", "上海证券交易所", "功率半导体 → MOSFET设计 → 中低压MOSFET"),
    ("300623", "捷捷微电", "江苏捷捷微电子股份有限公司", "深圳证券交易所", "功率半导体 → MOSFET设计 → 晶闸管/MOSFET/IGBT"),
    ("605358", "立昂微", "杭州立昂微电子股份有限公司", "上海证券交易所", "功率半导体 → MOSFET设计 → 功率二极管/MOSFET+硅片"),
]

# 公司→产品映射
COMPANY_PRODUCTS = {
    "600460": [
        "功率半导体", "IGBT", "MOSFET", "碳化硅器件", "电源管理IC",
        "MEMS传感器", "LED芯片", "车规级功率模块", "AI服务器电源模块",
    ],
    "688396": [
        "功率半导体", "MOSFET", "IGBT", "SiC碳化硅", "功率IC",
        "传感器", "MCU控制器",
    ],
    "600745": [
        "功率半导体", "车规级MOSFET", "功率二极管", "功率模组",
        "ESD保护器件", "逻辑器件", "双极性晶体管",
    ],
    "300373": [
        "功率半导体", "功率二极管", "整流桥", "MOSFET", "SiC碳化硅器件",
        "光伏二极管", "保护器件",
    ],
    "600360": [
        "功率半导体", "晶闸管", "中高压MOSFET", "功率二极管",
        "IGBT", "防护器件",
    ],
    "603290": [
        "功率半导体", "IGBT模块", "SiC碳化硅模块", "快恢复二极管",
        "车规级IGBT", "MOSFET", "IPM智能功率模块",
    ],
    "688711": [
        "功率半导体", "IGBT模块", "快恢复二极管", "FRD",
        "MOSFET", "SiC碳化硅器件",
    ],
    "300046": [
        "功率半导体", "大功率晶闸管", "IGBT模块",
        "脉冲功率开关", "大功率半导体组件",
    ],
    "605111": [
        "功率半导体", "中低压MOSFET", "IGBT",
        "电源管理IC", "SiC碳化硅器件",
    ],
    "300623": [
        "功率半导体", "晶闸管", "防护器件", "MOSFET",
        "IGBT", "SiC碳化硅器件",
    ],
    "605358": [
        "功率半导体", "功率二极管", "MOSFET",
        "硅片", "硅外延片",
    ],
}

# 产品上下游关系
PRODUCT_RELATIONS = [
    # 功率芯片核心产业链
    ("碳化硅衬底", "SiC碳化硅器件", "上游材料"),
    ("碳化硅衬底", "SiC碳化硅模块", "上游材料"),
    ("硅片", "功率半导体", "上游材料"),
    ("硅片", "MOSFET", "上游材料"),
    ("硅片", "IGBT", "上游材料"),
    ("硅片", "功率二极管", "上游材料"),
    ("硅外延片", "功率半导体", "上游材料"),
    ("硅外延片", "MOSFET", "上游材料"),
    # 功率芯片→应用
    ("功率半导体", "新能源汽车", "下游产品"),
    ("MOSFET", "充电器", "下游产品"),
    ("MOSFET", "电脑电源", "下游产品"),
    ("MOSFET", "AI服务器电源", "下游产品"),
    ("IGBT", "新能源车电控", "下游产品"),
    ("IGBT", "光伏逆变器", "下游产品"),
    ("IGBT", "工业变频器", "下游产品"),
    ("IGBT模块", "新能源车电控", "下游产品"),
    ("IGBT模块", "光伏逆变器", "下游产品"),
    ("IGBT模块", "工业变频器", "下游产品"),
    ("SiC碳化硅器件", "新能源车800V平台", "下游产品"),
    ("SiC碳化硅器件", "快充", "下游产品"),
    ("SiC碳化硅器件", "高压储能", "下游产品"),
    ("SiC碳化硅模块", "新能源车800V平台", "下游产品"),
    ("SiC碳化硅模块", "高压储能", "下游产品"),
    ("功率二极管", "充电桩", "下游产品"),
    ("功率二极管", "光伏储能", "下游产品"),
    ("晶闸管", "工控设备", "下游产品"),
    ("晶闸管", "特高压电网", "下游产品"),
    ("功率半导体", "家电", "下游产品"),
    ("功率半导体", "轨道交通", "下游产品"),
    ("氮化镓功率器件", "快充", "下游产品"),
    ("氮化镓功率器件", "AI算力电源", "下游产品"),
    ("快恢复二极管", "光伏逆变器", "下游产品"),
    ("快恢复二极管", "工业变频器", "下游产品"),
    # 产品层级关系
    ("功率半导体", "MOSFET", "产品小类"),
    ("功率半导体", "IGBT", "产品小类"),
    ("功率半导体", "功率二极管", "产品小类"),
    ("功率半导体", "晶闸管", "产品小类"),
    ("功率半导体", "SiC碳化硅器件", "产品小类"),
    ("功率半导体", "氮化镓功率器件", "产品小类"),
    ("功率半导体", "IPM智能功率模块", "产品小类"),
    ("IGBT", "IGBT模块", "产品小类"),
    ("IGBT模块", "车规级IGBT", "产品小类"),
    ("MOSFET", "车规级MOSFET", "产品小类"),
    ("MOSFET", "中低压MOSFET", "产品小类"),
    ("MOSFET", "中高压MOSFET", "产品小类"),
    ("功率模组", "IPM智能功率模块", "产品小类"),
    ("第三代半导体", "SiC碳化硅器件", "产品小类"),
    ("第三代半导体", "氮化镓功率器件", "产品小类"),
]


def import_power_chips():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    stats = {"companies_added": 0, "companies_skipped": 0,
             "products_added": 0, "product_links_added": 0,
             "relations_added": 0}

    # ---- 1. 公司入库 ----
    for code, name, fullname, location, route in COMPANIES:
        existing = conn.execute(
            "SELECT code FROM chain_companies WHERE code = ?", (code,)
        ).fetchone()
        if existing:
            stats["companies_skipped"] += 1
            continue
        conn.execute(
            "INSERT INTO chain_companies (code, name, fullname, location, list_time) VALUES (?,?,?,?,?)",
            (code, name, fullname, location, "")
        )
        stats["companies_added"] += 1

    # ---- 2. 公司-产品入库 ----
    for code, products in COMPANY_PRODUCTS.items():
        for product in products:
            existing = conn.execute(
                "SELECT id FROM chain_company_product WHERE company_code = ? AND product_name = ?",
                (code, product)
            ).fetchone()
            if existing:
                continue
            # 获取公司名
            row = conn.execute(
                "SELECT name FROM chain_companies WHERE code = ?", (code,)
            ).fetchone()
            company_name = row[0] if row else ""
            conn.execute(
                "INSERT INTO chain_company_product (company_code, company_name, product_name, rel) VALUES (?,?,?,?)",
                (code, company_name, product, "主营产品")
            )
            stats["products_added"] += 1

    # ---- 3. 产品上下游关系入库 ----
    for from_entity, to_entity, rel in PRODUCT_RELATIONS:
        existing = conn.execute(
            "SELECT id FROM chain_product_relation WHERE from_entity = ? AND to_entity = ? AND rel = ?",
            (from_entity, to_entity, rel)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO chain_product_relation (from_entity, to_entity, rel) VALUES (?,?,?)",
            (from_entity, to_entity, rel)
        )
        stats["relations_added"] += 1

    # ---- 4. 公司-产品链接数统计 ----
    stats["product_links_added"] = sum(len(p) for p in COMPANY_PRODUCTS.values())

    conn.commit()
    conn.close()

    print(f"[power_chips_import] ✅ 完成")
    print(f"  公司新增: {stats['companies_added']} / 跳过: {stats['companies_skipped']}")
    print(f"  产品关联: {stats['products_added']} 条新增")
    print(f"  产业关系: {stats['relations_added']} 条新增")
    return stats


if __name__ == "__main__":
    import_power_chips()
