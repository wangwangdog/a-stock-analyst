"""
全球供应链数据丰富 — 数据库Schema创建与数据导入
基于 chain.db 现有结构，新增：
  1. global_entities   — 统一实体表（跨数据源去重）
  2. global_relations  — 实体间关系表
  3. material_flows_ts — 全球物质流时间序列（1970-2019）
"""
import sqlite3
import json
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHAIN_DB = PROJECT_ROOT / "data" / "chain.db"

def create_schema(conn):
    """创建扩展表结构"""
    conn.executescript("""
        -- 统一实体表：跨数据源去重
        CREATE TABLE IF NOT EXISTS global_entities (
            id          TEXT PRIMARY KEY,   -- 全局唯一ID，如 "MF_China" / "EMRIO_12345"
            name        TEXT NOT NULL,       -- 实体名称
            type        TEXT NOT NULL,       -- country / company / industry / product / material
            source      TEXT NOT NULL,       -- material_flows / emrio / trase / chainkg
            external_id TEXT,                -- 原始数据源ID
            metadata    TEXT,                -- JSON 额外属性
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ge_name ON global_entities(name);
        CREATE INDEX IF NOT EXISTS idx_ge_type ON global_entities(type);
        CREATE INDEX IF NOT EXISTS idx_ge_source ON global_entities(source);

        -- 实体关系表
        CREATE TABLE IF NOT EXISTS global_relations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id    TEXT NOT NULL,       -- 源实体ID → global_entities.id
            target_id    TEXT NOT NULL,       -- 目标实体ID
            relation_type TEXT NOT NULL,       -- supplies_to / produces / upstream_of / downstream_of / contained_in
            weight       REAL DEFAULT 1.0,    -- 关系权重（交易金额/贸易量等）
            source       TEXT NOT NULL,        -- 数据来源
            metadata     TEXT,                 -- JSON
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_gr_src ON global_relations(source_id);
        CREATE INDEX IF NOT EXISTS idx_gr_tgt ON global_relations(target_id);
        CREATE INDEX IF NOT EXISTS idx_gr_rel ON global_relations(relation_type);

        -- 全球物质流时间序列（1970-2019）
        CREATE TABLE IF NOT EXISTS material_flows_ts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id   TEXT NOT NULL,        -- → global_entities.id (country)
            country     TEXT NOT NULL,         -- 冗余字段便于直接查询
            category    TEXT NOT NULL,         -- Biomass / Fossil fuels / Metal ores / Non-metallic minerals
            flow_name   TEXT NOT NULL,         -- DE / DMC / IMP / EXP / PTB 等
            flow_unit   TEXT NOT NULL,         -- t (吨)
            year        INTEGER NOT NULL,
            value       REAL,
            source      TEXT DEFAULT 'material_flows'
        );
        CREATE INDEX IF NOT EXISTS idx_mfts_entity ON material_flows_ts(entity_id);
        CREATE INDEX IF NOT EXISTS idx_mfts_country ON material_flows_ts(country);
        CREATE INDEX IF NOT EXISTS idx_mfts_flow ON material_flows_ts(flow_name);
        CREATE INDEX IF NOT EXISTS idx_mfts_year ON material_flows_ts(year);

        -- 实体映射表：跨数据源对齐
        CREATE TABLE IF NOT EXISTS entity_mapping (
            canonical_id TEXT,                -- ChainKnowledgeGraph 标准ID
            source_id    TEXT,                -- 外部数据源ID
            source       TEXT,                -- 数据源名称
            confidence   REAL DEFAULT 0.5,    -- 置信度
            PRIMARY KEY (source_id, source)
        );

        -- 元数据更新
        INSERT OR REPLACE INTO chain_meta (key, value) 
        VALUES ('schema_version', '2.0');
    """)


def import_material_flows(csv_path: str, conn, limit: int | None = None):
    """导入全球物质流CSV → material_flows_ts 表
    
    CSV格式: Country,Category,Flow name,Flow code,Flow unit,1970,1971,...,2019
    """
    country_entities = set()
    row_count = 0
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    countries_seen = set()
    
    for row in rows:
        country = row.get('Country')
        category = row.get('Category')
        flow_name = row.get('Flow name')
        flow_unit = row.get('Flow unit')
        
        # 跳过不完整的行（截断文件）
        if not country or not category or not flow_name:
            continue
        
        # 确保国家实体已创建
        entity_id = f"MF_{country}"
        if entity_id not in country_entities:
            meta = json.dumps({"category_hint": category})
            conn.execute(
                "INSERT OR IGNORE INTO global_entities (id, name, type, source, metadata) VALUES (?, ?, ?, ?, ?)",
                (entity_id, country, 'country', 'material_flows', meta)
            )
            country_entities.add(entity_id)
        
        # 展开年份列
        for col in row:
            if col.isdigit() and 1970 <= int(col) <= 2025:
                year = int(col)
                val_str = (row.get(col) or '').strip()
                if val_str and val_str.replace('.', '').replace('-', '').isdigit():
                    value = float(val_str)
                    if value == 0:
                        continue  # 跳过全零行压缩存储
                    conn.execute(
                        """INSERT INTO material_flows_ts 
                           (entity_id, country, category, flow_name, flow_unit, year, value)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (entity_id, country, category, flow_name, flow_unit, year, value)
                    )
                    row_count += 1
        
        if limit and row_count >= limit:
            break
    
    conn.commit()
    return len(country_entities), row_count


def map_to_chainkg(conn):
    """将材料流实体与中国产业链实体做关联映射
    
    策略：产品名模糊匹配 → 公司→行业→原料关联
    """
    # 1. 为每个国家的材料流数据，在产品表中寻找关联
    # 基础材料映射：material_flows 中的材料类别 ↔ chain_product_relation 中的产品名
    material_category_map = {
        'Metal ores': ['铁矿', '铜矿', '铝矿', '锌矿', '镍矿', '铅矿', '锡矿', '锰矿', 
                       '金矿', '银矿', '钨矿', '钼矿', '稀土', '钢材', '铝材', '铜材',
                       '金属', '矿', '钢', '铝', '铜', '锌', '镍', '铅', '锡'],
        'Fossil fuels': ['石油', '原油', '天然气', '煤炭', '煤', '汽油', '柴油', '燃料油',
                        '液化气', '焦炭', '石脑油'],
        'Biomass': ['木材', '木料', '纸浆', '纸张', '橡胶', '棉花', '棉', '粮食',
                   '大豆', '玉米', '小麦', '稻谷', '糖', '植物油', '纺织'],
        'Non-metallic minerals': ['水泥', '玻璃', '石材', '石灰', '石膏', '砂石',
                                 '陶瓷', '石墨', '硅', '磷', '钾肥', '化肥'],
    }
    
    # 2. 对每个国家实体，寻找其与产品的关联
    # 这里先插入基础映射关系
    for country_entity_id, in conn.execute(
        "SELECT id FROM global_entities WHERE type='country' AND source='material_flows'"
    ).fetchall():
        country = country_entity_id.replace('MF_', '')
        
        # 如果是中国，建立与国家→行业的映射
        if country == 'China':
            # 获取中国在chainkg中的主要行业
            for industry_row in conn.execute(
                "SELECT DISTINCT industry_name FROM chain_company_industry"
            ).fetchall():
                industry = industry_row[0]
                # 映射国家→行业关系
                conn.execute(
                    """INSERT OR IGNORE INTO global_relations 
                       (source_id, target_id, relation_type, source, metadata)
                       VALUES (?, ?, ?, ?, ?)""",
                    (country_entity_id, f"IND_{industry}", 'affiliated_with', 'material_flows',
                     json.dumps({"note": "China industry affiliation via ChainKnowledgeGraph", "weight": 1.0}))
                )
    
    conn.commit()
    return conn.total_changes


def main():
    conn = sqlite3.connect(str(CHAIN_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/global_material_flows_full.csv"
    
    if not Path(csv_path).exists():
        print(f"❌ CSV 文件不存在: {csv_path}")
        print(f"   请先下载: https://energydata.info/dataset/8121a8bc-37b6-408a-91b4-b015c299b349/")
        sys.exit(1)
    
    print("📐 创建扩展表结构...")
    create_schema(conn)
    
    print(f"📥 导入全球物质流数据: {csv_path}")
    country_count, row_count = import_material_flows(csv_path, conn)
    print(f"   国家: {country_count} | 时间序列行: {row_count}")
    
    print("🔗 建立与中国产业链的实体映射...")
    map_to_chainkg(conn)
    
    # 统计
    entities = conn.execute("SELECT COUNT(*) FROM global_entities").fetchone()[0]
    relations = conn.execute("SELECT COUNT(*) FROM global_relations").fetchone()[0]
    ts_rows = conn.execute("SELECT COUNT(*) FROM material_flows_ts").fetchone()[0]
    
    print(f"\n✅ 导入完成:")
    print(f"   global_entities:    {entities} 个")
    print(f"   global_relations:   {relations} 条")
    print(f"   material_flows_ts:  {ts_rows} 行")
    
    # 预览
    print("\n📊 物质流分类统计:")
    for row in conn.execute(
        "SELECT flow_name, COUNT(*) as cnt FROM material_flows_ts GROUP BY flow_name ORDER BY cnt DESC LIMIT 10"
    ):
        print(f"   {row[0]:20s} {row[1]:>8,} 行")
    
    print("\n🌍 样本数据 (中国, 2020年以后):")
    for row in conn.execute(
        """SELECT country, category, flow_name, year, value 
           FROM material_flows_ts 
           WHERE country='China' AND year >= 2020 
           ORDER BY year, category, flow_name 
           LIMIT 15"""
    ):
        print(f"   {row[0]:12s} | {row[1]:25s} | {row[2]:10s} | {row[3]} | {row[4]:>14,.0f}")
    
    conn.close()


if __name__ == "__main__":
    main()
