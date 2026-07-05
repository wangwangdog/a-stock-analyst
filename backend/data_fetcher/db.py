"""
数据库管理 — 所有扩展数据表的建表、写库、查询
数据标准统一：
  - volume: REAL, 单位=股 (shares)
  - amount/turnover/fund: REAL, 单位=元 (CNY)
  - price: REAL, 单位=元
  - market_cap: REAL, 单位=元
  - date: TEXT 'YYYY-MM-DD'
  - code: TEXT, 带前缀 (SH.600000, SZ.000001)
"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"


def get_db_path() -> str:
    return DB_PATH


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


# ============================================================
# 建表（幂等：IF NOT EXISTS）
# ============================================================

CREATE_LIMIT_UP_POOL = """
CREATE TABLE IF NOT EXISTS limit_up_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,              -- SZ.000001
    name TEXT,
    trade_date TEXT NOT NULL,         -- YYYY-MM-DD
    pool_type TEXT NOT NULL,          -- 'zt'(涨停) / 'zb'(炸板) / 'dt'(跌停) / 'yzt'(昨涨停今表现)
    price REAL,                       -- 元
    pct REAL,                         -- 涨跌幅 %
    amount REAL,                      -- 成交额 元
    turnover REAL,                    -- 换手率 %
    seal_fund REAL,                   -- 封单资金 元
    limit_days INTEGER,               -- 连板数
    first_seal TEXT,                  -- 首次封板时间
    last_seal TEXT,                   -- 最后封板时间
    break_times INTEGER,              -- 炸板次数
    industry TEXT,                    -- 所属行业
    zt_stat TEXT,                     -- N天M板描述
    board_amount REAL,                -- 板上成交额 元(仅跌停池)
    amplitude REAL,                   -- 振幅 %(仅炸板池)
    speed REAL,                       -- 涨速 %(仅炸板池)
    seal_rate REAL,                   -- 封板成功率 0~1(同花顺)
    reason TEXT,                      -- 涨停原因题材(同花顺)
    board_type TEXT,                  -- 板型: 一字/换手/T字(同花顺)
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, trade_date, pool_type)
);
"""

CREATE_DRAGON_TIGER = """
CREATE TABLE IF NOT EXISTS dragon_tiger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,              -- SZ.000001
    name TEXT,
    trade_date TEXT NOT NULL,         -- YYYY-MM-DD
    reason TEXT,                      -- 上榜原因
    net_buy REAL,                    -- 净买入额 元
    total_buy REAL,                  -- 总买入额 元
    total_sell REAL,                 -- 总卖出额 元
    turnover REAL,                   -- 换手率 %
    buy_seats TEXT,                   -- 买入席位TOP5(JSON)
    sell_seats TEXT,                  -- 卖出席位TOP5(JSON)
    inst_buy REAL,                   -- 机构买入 元
    inst_sell REAL,                  -- 机构卖出 元
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, trade_date)
);
"""

CREATE_MARGIN_TRADING = """
CREATE TABLE IF NOT EXISTS margin_trading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    date TEXT NOT NULL,               -- YYYY-MM-DD
    margin_balance REAL,              -- 融资余额 元
    margin_buy REAL,                  -- 融资买入额 元
    margin_repay REAL,               -- 融资偿还额 元
    short_sell_balance REAL,          -- 融券余额 元
    short_sell_sell REAL,             -- 融券卖出额 元
    short_sell_repay REAL,           -- 融券偿还额 元
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, date)
);
"""

CREATE_BLOCK_TRADE = """
CREATE TABLE IF NOT EXISTS block_trade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    trade_date TEXT NOT NULL,         -- YYYY-MM-DD
    price REAL,                       -- 成交价 元
    volume REAL,                      -- 成交量 股
    amount REAL,                      -- 成交额 元
    premium_rate REAL,                -- 溢价率 %
    buyer TEXT,                       -- 买方营业部
    seller TEXT,                      -- 卖方营业部
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, trade_date, buyer, seller)
);
"""

CREATE_HOLDER_COUNT = """
CREATE TABLE IF NOT EXISTS holder_count (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    report_date TEXT NOT NULL,         -- YYYY-MM-DD 截止日期
    holder_count REAL,                -- 股东户数
    change_pct REAL,                  -- 环比变化 %
    avg_shares REAL,                  -- 户均持股 股
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, report_date)
);
"""

CREATE_DIVIDEND = """
CREATE TABLE IF NOT EXISTS dividend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    announce_date TEXT NOT NULL,       -- 公告日期
    plan TEXT,                         -- 分红方案描述
    cash_dividend REAL,                -- 每股派息 元
    bonus_shares REAL,                 -- 每股送股
    transfer_shares REAL,              -- 每股转增
    progress TEXT,                     -- 进度状态
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, announce_date, plan)
);
"""

CREATE_NORTHBOUND_FLOW = """
CREATE TABLE IF NOT EXISTS northbound_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,         -- YYYY-MM-DD
    hgt_net REAL,                      -- 沪股通净流入 元
    sgt_net REAL,                      -- 深股通净流入 元
    total_net REAL,                    -- 合计净流入 元
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

CREATE_FUND_FLOW_DAILY = """
CREATE TABLE IF NOT EXISTS fund_flow_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    date TEXT NOT NULL,               -- YYYY-MM-DD
    main_net REAL,                    -- 主力净流入 元
    super_large_net REAL,             -- 超大单净流入 元
    large_net REAL,                   -- 大单净流入 元
    medium_net REAL,                  -- 中单净流入 元
    small_net REAL,                   -- 小单净流入 元
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, date)
);
"""

CREATE_LOCKUP_CALENDAR = """
CREATE TABLE IF NOT EXISTS lockup_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    unlock_date TEXT NOT NULL,         -- YYYY-MM-DD 解禁日
    shares REAL,                      -- 解禁数量 股
    ratio REAL,                       -- 解禁占总股本比例 %
    amount REAL,                      -- 解禁市值 元
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, unlock_date)
);
"""

CREATE_INDUSTRY_RANKING = """
CREATE TABLE IF NOT EXISTS industry_ranking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_code TEXT NOT NULL,       -- 东财行业码
    industry_name TEXT NOT NULL,
    date TEXT NOT NULL,               -- YYYY-MM-DD
    change_pct REAL,                  -- 涨幅 %
    up_count INTEGER,                 -- 上涨家数
    down_count INTEGER,               -- 下跌家数
    total_stocks INTEGER,             -- 总家数
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(industry_code, date)
);
"""

CREATE_STOCK_CONCEPT = """
CREATE TABLE IF NOT EXISTS stock_concept (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    concept_name TEXT NOT NULL,
    concept_code TEXT,                -- BK码
    category TEXT,                    -- 行业/概念/地域
    date TEXT NOT NULL,               -- YYYY-MM-DD 记录日期
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, concept_name, date)
);
"""

CREATE_ETF_OPTION_QUOTE = """
CREATE TABLE IF NOT EXISTS etf_option_quote (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying TEXT NOT NULL,          -- 标的: 510050/510300/588000/510500
    contract_code TEXT NOT NULL,
    name TEXT,
    call_put TEXT NOT NULL,            -- 'CALL' / 'PUT'
    strike REAL,                       -- 行权价 元
    expiry TEXT,                       -- 到期日 YYYY-MM-DD
    last_price REAL,                   -- 最新价 元
    bid_price REAL,                    -- 买一价 元
    ask_price REAL,                    -- 卖一价 元
    bid_vol REAL,                      -- 买一量 张
    ask_vol REAL,                      -- 卖一量 张
    open_interest REAL,                -- 持仓量 张
    volume REAL,                       -- 成交量 张
    amount REAL,                       -- 成交额 元
    pct REAL,                          -- 涨跌幅 %
    delta REAL,                        -- Delta
    gamma REAL,                        -- Gamma
    theta REAL,                        -- Theta
    vega REAL,                         -- Vega
    iv REAL,                           -- 隐含波动率(小数)
    theory_price REAL,                 -- 理论价值 元
    snapshot_time TEXT,                -- 快照时间
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(contract_code, snapshot_time)
);
"""

CREATE_INVESTOR_QA = """
CREATE TABLE IF NOT EXISTS investor_qa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    question_date TEXT,               -- YYYY-MM-DD
    question TEXT,                    -- 投资者提问
    answer_date TEXT,                 -- YYYY-MM-DD
    answer TEXT,                      -- 公司回复
    qa_id TEXT,                       -- 互动易问答ID(去重用)
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, qa_id)
);
"""

CREATE_THS_HOT_LIST = """
CREATE TABLE IF NOT EXISTS ths_hot_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    rank INTEGER,                     -- 排名
    rank_change INTEGER,              -- 排名变化
    popularity REAL,                  -- 人气值
    concept_tags TEXT,                -- 概念标签(JSON)
    period TEXT NOT NULL,             -- hour/day/week
    snapshot_time TEXT NOT NULL,       -- 快照时间
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, period, snapshot_time)
);
"""

CREATE_STOCK_INDUSTRY = """
CREATE TABLE IF NOT EXISTS stock_industry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    industry_name TEXT NOT NULL,       -- 行业名称
    industry_code TEXT,               -- 东财行业码
    category TEXT NOT NULL,            -- HY(行业) / GN(概念) / DQ(地域)
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code, industry_name, category)
);
"""


# ============================================================
# 建立所有表
# ============================================================

ALL_DDLS = [
    CREATE_LIMIT_UP_POOL,
    CREATE_DRAGON_TIGER,
    CREATE_MARGIN_TRADING,
    CREATE_BLOCK_TRADE,
    CREATE_HOLDER_COUNT,
    CREATE_DIVIDEND,
    CREATE_NORTHBOUND_FLOW,
    CREATE_FUND_FLOW_DAILY,
    CREATE_LOCKUP_CALENDAR,
    CREATE_INDUSTRY_RANKING,
    CREATE_STOCK_CONCEPT,
    CREATE_ETF_OPTION_QUOTE,
    CREATE_INVESTOR_QA,
    CREATE_THS_HOT_LIST,
    CREATE_STOCK_INDUSTRY,
]


def create_all_tables():
    """幂等建表"""
    conn = get_conn()
    for ddl in ALL_DDLS:
        conn.execute(ddl)
    conn.commit()
    conn.close()


# ============================================================
# 通用 upsert 辅助
# ============================================================

def _upsert(table: str, data: dict, unique_cols: list[str], extra_types: Optional[dict] = None):
    """通用 upsert：用 unique_cols 做去重判断"""
    cols = list(data.keys())
    placeholders = ','.join(['?' for _ in cols])
    update_set = ','.join([f'{c}=excluded.{c}' for c in cols if c not in unique_cols and c != 'created_at'])
    sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT ({','.join(unique_cols)}) DO UPDATE SET {update_set}")
    conn = get_conn()
    conn.execute(sql, [data.get(c) for c in cols])
    conn.commit()
    conn.close()


# ============================================================
# 每个表专用的 upsert 函数
# ============================================================

def upsert_limit_up_pool(row: dict):
    _upsert('limit_up_pool', row, ['code', 'trade_date', 'pool_type'])

def upsert_dragon_tiger(row: dict):
    _upsert('dragon_tiger', row, ['code', 'trade_date'])

def upsert_margin_trading(row: dict):
    _upsert('margin_trading', row, ['code', 'date'])

def upsert_block_trade(row: dict):
    _upsert('block_trade', row, ['code', 'trade_date', 'buyer', 'seller'])

def upsert_holder_count(row: dict):
    _upsert('holder_count', row, ['code', 'report_date'])

def upsert_dividend(row: dict):
    _upsert('dividend', row, ['code', 'announce_date', 'plan'])

def upsert_northbound_flow(row: dict):
    _upsert('northbound_flow', row, ['date'])

def upsert_fund_flow_daily(row: dict):
    _upsert('fund_flow_daily', row, ['code', 'date'])

def upsert_lockup_calendar(row: dict):
    _upsert('lockup_calendar', row, ['code', 'unlock_date'])

def upsert_industry_ranking(row: dict):
    _upsert('industry_ranking', row, ['industry_code', 'date'])

def upsert_stock_concept(row: dict):
    _upsert('stock_concept', row, ['code', 'concept_name', 'date'])

def upsert_etf_option_quote(row: dict):
    _upsert('etf_option_quote', row, ['contract_code', 'snapshot_time'])

def upsert_investor_qa(row: dict):
    conn = get_conn()
    sql = ("INSERT OR IGNORE INTO investor_qa "
           "(code, name, question_date, question, answer_date, answer, qa_id) "
           "VALUES (?, ?, ?, ?, ?, ?, ?)")
    conn.execute(sql, [row.get(k) for k in ['code','name','question_date','question','answer_date','answer','qa_id']])
    conn.commit()
    conn.close()

def upsert_ths_hot_list(row: dict):
    _upsert('ths_hot_list', row, ['code', 'period', 'snapshot_time'])

def upsert_stock_industry(row: dict):
    _upsert('stock_industry', row, ['code', 'industry_name', 'category'])


# ============================================================
# 查询辅助
# ============================================================

def query(table: str, where: str = "", params: list = None, limit: int = 100):
    conn = get_conn()
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY id DESC LIMIT {limit}"
    cur = conn.execute(sql, params or [])
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


if __name__ == "__main__":
    create_all_tables()
    print("✅ 所有扩展数据表创建完成")
