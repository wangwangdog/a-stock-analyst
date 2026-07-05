"""
导入富创精密 (688409) → Marvell/MRV / Lumentum(LITE) 供应链数据

富创精密给 Marvell 和 Lumentum 供货光模块/光引擎封测制造
"""
import sqlite3
from pathlib import Path

DB = Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite")

def main():
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # 1. 海外实体 — Marvell / Lumentum
    overseas = [
        ("MRVL", "Marvell", "Marvell Technology Inc.", "美国"),
        ("LITE", "Lumentum", "Lumentum Holdings Inc.", "美国"),
    ]
    for code, name, fullname, country in overseas:
        conn.execute(
            "INSERT OR IGNORE INTO chain_overseas_entities(code, name, fullname, country) VALUES (?,?,?,?)",
            (code, name, fullname, country),
        )
        print(f"  [实体] {code} {name}")
    
    # 2. 新分类 — 光模块/光引擎封装制造
    conn.execute(
        "INSERT OR IGNORE INTO chain_supply_categories(id, label) VALUES ('opto_packaging', '光模块/光引擎封装制造')"
    )
    print("  [分类] opto_packaging 光模块/光引擎封装制造")

    # 3. 富创精密 — 上市公司
    conn.execute(
        """INSERT OR IGNORE INTO chain_companies(code, name, fullname, location, list_time)
           VALUES ('688409.SH', '富创精密', '沈阳富创精密设备股份有限公司',
                   '上海证券交易所', '2022-10-10')"""
    )
    print("  [公司] 688409.SH 富创精密")

    # 4. 供应链关系
    relations = [
        # Marvell ← 富创精密: 光引擎OE封装和制造
        ("MRVL", "Marvell", "688409.SH", "富创精密",
         "opto_packaging", "exclusive",
         "成功导入Marvell，产品为光引擎OE封装和制造，2028年起量。"
         "由子公司富创优越(31条产线)执行，含FlipChip先进封装工艺。"),
        # Lumentum ← 富创精密: 1.6T光模块
        ("LITE", "Lumentum", "688409.SH", "富创精密",
         "opto_packaging", "exclusive",
         "合作1.6T光模块产品，2026年采购金额大幅增长至9亿元(开始显著放量)，"
         "2027年或将继续高增长。富创优越在其产品份额为50%~70%。"
         "同时协同开发新一代3.2T、NPO/CPO技术。"),
    ]
    for bc, bn, sc, sn, cat, cov, notes in relations:
        existing = conn.execute(
            "SELECT id FROM chain_supply_relations WHERE buyer_code=? AND supplier_code=? AND category=?",
            (bc, sc, cat)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE chain_supply_relations SET notes=?, coverage=?, buyer_name=?, supplier_name=? WHERE id=?",
                (notes, cov, bn, sn, existing["id"])
            )
            print(f"  [更新] {bn} ← {sn} ({cat})")
        else:
            conn.execute(
                """INSERT INTO chain_supply_relations(buyer_code, buyer_name, supplier_code, supplier_name, category, coverage, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (bc, bn, sc, sn, cat, cov, notes)
            )
            print(f"  [新增] {bn} ← {sn} ({cat})")

    conn.commit()
    conn.close()
    print("\n✅ 导入完成")


if __name__ == "__main__":
    main()
