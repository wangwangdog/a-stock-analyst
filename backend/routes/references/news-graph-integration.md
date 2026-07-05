# 新闻→供应链图谱 API 集成 — news-supply-chain 端点

**文件**: `backend/routes/chain.py` → `get_news_supply_chain()`
**路由**: `GET /api/v1/chain/news-supply-chain?title=...&summary=...`

---

## 匹配优先级（自上而下，命中即返回）

```
新闻标题/摘要
  │
  ├─（1）FOREIGN_MAP 硬编码匹配（英文名: nvidia/tsmc/amd/...）
  │     → 设 foreign_entity + cn_entity，沿用旧的单公司对标模式
  │
  ├─（2）chain_overseas_entities 数据库匹配（中文/英文/别名/股票代码）
  │     ├─ 完整名称含在标题中 → 精准命中
  │     ├─ 中文名拆词匹配（"海力士" → "SK海力士"）
  │     ├─ 英文/拼音别名（samsung/hynix/micron/삼성/하이닉스）
  │     ├─ 通用英文名匹配：oe["code"].lower() + oe["name"].lower()
  │     └─ 股票代码匹配：$MRVL / $LITE（\$[A-Z]{1,5}）
  │     → 单家海外巨头供应链图谱
  │
  ├─（3）存储行业关键词触发（存储/hbm/内存/dram/nand/闪存）
  │     → __ALL__ 模式：同时查三家海外巨头的供应链
  │     → 去重供应商 + 合并品类
  │
  └─（4）CN_TOPIC_MAP + chain_companies 公司名模糊搜索
       → 旧模式：国内公司 + 国外对标（无供应链数据）
```

**注意**: CN_TOPIC_MAP 截胡问题 — 当标题含"芯片"时命中链→中芯国际。
需要存储关键词（存储/HBM/内存等）交叉命中时触发供应链模式，
已在步骤（3）中独立处理，不受 CN_TOPIC_MAP 影响。

**2026-06-29 新增**：中英文名全能匹配 + $TICKER 匹配。sqlite3.Row 对象没有 .get()，用 oe["name"]。

---

## 返回格式

```json
{
  "status": "ok",
  "title": "三星存储扩产",
  "mode": "supply_chain",
  "main_domestic": {"name": "23家供应商"},
  "main_foreign": {"name": "三星"},
  "steps": [
    {"icon": "🔍", "label": "新闻分析：三星存储扩产..."},
    {"icon": "🌐", "label": "识别海外实体：三星"},
    {"icon": "🔗", "label": "查询到 23 家供应商，6 个品类"}
  ],
  "graph_domestic": {
    "nodes": [
      {"id": "cat_equity_bonding", "label": "股权绑定", "type": "category"},
      {"id": "co_600667.SH", "label": "太极实业", "type": "company"},
      {"id": "co_002409.SZ", "label": "雅克科技", "type": "company"},
      {"id": "cat_hbm_material", "label": "HBM材料", "type": "category"}
    ],
    "edges": [
      {"source": "co_600667.SH", "target": "cat_equity_bonding",
       "label": "所属品类", "edgeType": "belongs_to"},
      {"source": "co_002409.SZ", "target": "cat_hbm_material",
       "label": "所属品类", "edgeType": "belongs_to"}
    ]
  },
  "graph_foreign": {
    "nodes": [
      {"id": "foreign_SAMSUNG", "label": "三星", "type": "company"}
    ],
    "edges": []
  },
  "bridges": [
    {"source": "cat_hbm_material", "source_type": "category",
     "target": "foreign_SAMSUNG", "target_type": "company",
     "label": "供应", "edgeType": "supply"}
  ]
}
```

### 节点类型

| type | 说明 | 示例 ID |
|------|------|---------|
| `category` | 供应链品类分组 | `cat_equity_bonding` |
| `company` | 国内供应商 / 海外实体 | `co_600667.SH` / `foreign_SAMSUNG` |

### 边类型

| edgeType | 方向 | 说明 |
|----------|------|------|
| `belongs_to` | 供应商 → 品类 | 该公司属于该供应品类 |
| `supply` | 品类 → 海外（桥梁） | 该品类供应海外巨头 |

---

## __ALL__ 模式（批量查询）

当触发存储行业关键词时，`overseas_code = "__ALL__"`：

```sql
-- 查所有海外实体
SELECT code, name FROM chain_overseas_entities;

-- 查所有供应链（IN 查询）
SELECT r.buyer_code, r.category, c.label as cat_label,
       r.supplier_code, r.supplier_name, r.notes
FROM chain_supply_relations r
LEFT JOIN chain_supply_categories c ON r.category = c.id
WHERE r.buyer_code IN ('SAMSUNG','SK_HYNIX','MICRON')
ORDER BY r.buyer_code, r.category, r.supplier_code;
```

特点：
- 国内节点去重（同一供应商供多家只出现一次）
- 品类节点合并（共享品类不重复）
- 国外图谱显示 3 个海外实体节点
- 桥梁连接每个品类 → 每个海外实体

---

## 别名匹配表

```python
aliases = {
    "SAMSUNG":  ["samsung", "삼성"],
    "SK_HYNIX": ["sk hynix", "hynix", "하이닉스"],
    "MICRON":   ["micron", "마이크론"],
}
```

**通用英文名匹配**（2026-06-29 新增）：  
除硬编码别名外，还会自动尝试：
- **中文/英文名匹配**：`oe_name in title or oe_name in text_lc` 直接匹配
- **英文代码匹配**：`oe["code"].lower()`（如 "marvell" / "lite"）在文本中出现
- **英文名称匹配**：`oe["name"].lower()`（如 "marvell" / "lumentum"）在文本中出现  
- **股票代码匹配**：`\$[A-Z]{1,5}` 正则提取（如 `$MRVL` → 匹配 MRVL 实体）

⚠️ **sqlite3.Row 陷阱**：`sqlite3.Row` 对象没有 `.get()` 方法（只有 `[]` 下标操作），用 `oe.get("name")` 会抛 `AttributeError` 被 `except: pass` 吞掉导致匹配静默失败。必须用 `oe["name"]`。

中文名拆词匹配：`re.findall(r'[\u4e00-\u9fff]{2,}', oe_name)` 取 2 字以上片段。

---

## 数据库信息

- **路径**: `/mnt/disk990g/sqlite-data/chanlun_klines.sqlite`（25GB）
- **连接**: `_get_chain_conn()` → `sqlite3.connect(str(_main_db))`，`row_factory = sqlite3.Row`
- **检查**: `_check_chain_db()` 检查 `chain_companies` 和 `chain_supply_relations` 表存在

### 相关表

| 表 | 用途 | 关键列 |
|----|------|--------|
| `chain_overseas_entities` | 海外实体 | code, name, fullname, country |
| `chain_supply_categories` | 供应品类 | id, label |
| `chain_supply_relations` | 供应链关系 | buyer_code, supplier_code, supplier_name, category, coverage, notes |
| `chain_companies` | A股公司 | code, name |

### 品类（8个）

| id | label |
|----|-------|
| equity_bonding | 股权绑定 |
| hbm_material | HBM材料 |
| packaging_test | 封测代工 |
| module_distribution | 模组分销 |
| chemical_materials | 电子化学品/靶材 |
| equipment_testing | 设备检测 |
| chip_solution | 配套芯片 |
| opto_packaging | 光模块/光引擎封装制造 |

### 海外实体（5家）

| code | name | 备注 |
|------|------|------|
| SAMSUNG | 三星 | 韩国存储巨头 |
| SK_HYNIX | SK海力士 | 韩国存储巨头 |
| MICRON | 美光 | 美国存储巨头 |
| MRVL | Marvell | 美国芯片设计（光引擎OE） |
| LITE | Lumentum | 美国光模块/光通信 |

### 供应链关系（66条）

已有 3 家存储巨头（64条）+ 2026-06-29 新增 2 条：

| buyer_code | supplier_code | supplier_name | category | 说明 |
|-----------|--------------|--------------|----------|------|
| MRVL | 688409.SH | 富创精密 | opto_packaging | 光引擎OE封装和制造，2028年起量 |
| LITE | 688409.SH | 富创精密 | opto_packaging | 1.6T光模块，2026年采购9亿，份额50-70% |

---

## 常见问题

### 缓存问题（pyc）
`_chain_db` → `_main_db` 重命名后，删除 `__pycache__` 和 `*.pyc`:
```bash
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find . -name '*.pyc' -delete 2>/dev/null
```

### 主库被清空
工作区 `chanlun_klines.sqlite` 可能 0 字节。
真实数据在 `/mnt/disk990g/sqlite-data/chanlun_klines.sqlite`。
检查 `_main_db` 路径配置。

### 路由前缀
所有 chain 路由前缀是 `/api/v1`，完整路径如：
- `GET /api/v1/chain/news-supply-chain`
- `GET /api/v1/chain/news-graph`
- `GET /api/v1/chain/expand-smart`
- `GET /api/v1/chain/stock/{code}`
