# A-Stock Analyst 项目结构分析报告

> **作者**: 胖磊 🦞  
> **类型**: A 股数据分析 Web 工具（手机端适配）  
> **分析日期**: 2026-05-09

---

## 一、目录树

```
a-stock-analyst/
├── .env                          # 环境变量（API Key 等）
├── .gitignore                    # Git 忽略规则
├── package.json                  # 根 package（puppeteer 依赖）
├── package-lock.json
├── README.md
│
├── backend/                      # 🎯 Python FastAPI 后端
│   ├── main.py                   # FastAPI 主入口（端口 8765）
│   ├── config.py                 # 全局配置（DB 路径、校验容差）
│   ├── config/                   # JSON 配置
│   │   ├── models.json           # LLM 模型配置
│   │   ├── pricing.json          # 价格配置
│   │   └── settings.json         # 系统设置
│   ├── requirements.txt          # 核心依赖
│   ├── requirements-all.txt      # 完整依赖
│   │
│   ├── routes/                   # 📡 API 路由层
│   │   ├── __init__.py
│   │   ├── kline.py              # K线数据 / 基本面 / 选股
│   │   ├── ai.py                 # AI 快速/深度分析（含 SSE 流式）
│   │   ├── strategy.py           # 量化选股（Sequoia-X 6大策略）
│   │   ├── chanlun.py            # 缠论技术分析（4种算法对比）
│   │   ├── auth.py               # 简易登录 / 分析缓存
│   │   └── favorites.py          # 自选股 CRUD
│   │
│   ├── data/                     # 💾 数据获取与缓存层
│   │   ├── cache.py              # SQLite 缓存层（kline_cache 表）
│   │   ├── validator.py          # 双源交叉校验（AKShare vs Baostock）
│   │   ├── akshare_fetcher.py    # AKShare 数据获取
│   │   ├── baostock_fetcher.py   # Baostock 数据获取
│   │   ├── sequoia_engine.py     # Sequoia-X 数据引擎 + 策略调度
│   │   ├── sequoia_v2.db         # Sequoia-X 数据库
│   │   └── stock_cache.db        # 主缓存数据库（.gitignore 排除）
│   │
│   ├── analysis/                 # 📊 技术分析模块
│   │   ├── indicators.py         # 技术指标（MA, MACD, RSI, Bollinger）
│   │   ├── fundamentals.py       # 基本面数据（东方财富 + AKShare）
│   │   └── tushare_analysis.py   # Tushare 扩展分析
│   │
│   ├── sequoia_x/                # 🌲 Sequoia-X 量化选股引擎
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic 配置（DB 路径、飞书 Webhook）
│   │   │   ├── logger.py         # 日志模块
│   │   │   └── __init__.py
│   │   ├── data/
│   │   │   ├── engine.py         # DataEngine（baostock 同步 + SQLite 读写）
│   │   │   └── __init__.py
│   │   ├── strategy/             # 📈 6 大选股策略
│   │   │   ├── base.py           # BaseStrategy 抽象基类
│   │   │   ├── ma_volume.py      # 均线放量（金叉+放量1.5倍）
│   │   │   ├── turtle_trade.py   # 海龟交易（唐奇安通道突破）
│   │   │   ├── high_tight_flag.py# 高窄旗形
│   │   │   ├── limit_up_shakeout.py# 涨停洗盘
│   │   │   ├── uptrend_limit_down.py# 跌停反包
│   │   │   ├── rps_breakout.py   # RPS 极强动量突破
│   │   │   └── __init__.py
│   │   ├── notify/
│   │   │   └── feishu.py         # 飞书通知推送
│   │   └── __init__.py
│   │
│   ├── tradingagents/            # 🤖 TradingAgents-CN 多 Agent 研判系统
│   │   ├── default_config.py     # 默认配置
│   │   ├── agents/
│   │   │   ├── analysts/         # 分析师 Agent
│   │   │   │   ├── market_analyst.py       # 市场环境分析
│   │   │   │   ├── fundamentals_analyst.py # 基本面分析
│   │   │   │   ├── china_market_analyst.py # A股市场专项
│   │   │   │   ├── news_analyst.py         # 新闻情绪
│   │   │   │   └── social_media_analyst.py # 社交媒体情绪
│   │   │   ├── managers/         # 管理 Agent
│   │   │   │   ├── research_manager.py     # 研判管理
│   │   │   │   └── risk_manager.py         # 风险管理
│   │   │   ├── researchers/      # 研究员 Agent（辩论）
│   │   │   │   ├── bull_researcher.py      # 多头研究员
│   │   │   │   └── bear_researcher.py      # 空头研究员
│   │   │   ├── risk_mgmt/        # 风控辩论
│   │   │   │   ├── aggresive_debator.py
│   │   │   │   ├── conservative_debator.py
│   │   │   │   └── neutral_debator.py
│   │   │   ├── trader/
│   │   │   │   └── trader.py     # 交易员（最终决策）
│   │   │   └── utils/
│   │   │       ├── agent_states.py
│   │   │       ├── agent_utils.py
│   │   │       ├── chromadb_config.py
│   │   │       ├── google_tool_handler.py
│   │   │       ├── instrument_utils.py
│   │   │       └── memory.py
│   │   ├── api/
│   │   │   └── stock_api.py      # 股票数据 API
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── config_manager.py
│   │   │   ├── database_config.py
│   │   │   ├── env_utils.py
│   │   │   ├── mongodb_storage.py
│   │   │   ├── providers_config.py
│   │   │   ├── runtime_settings.py
│   │   │   ├── tushare_config.py
│   │   │   └── usage_models.py
│   │   ├── constants/
│   │   │   ├── __init__.py
│   │   │   └── data_sources.py
│   │   ├── dataflows/            # 数据流层
│   │   │   ├── cache/            # 多级缓存系统
│   │   │   │   ├── __init__.py
│   │   │   │   ├── adaptive.py
│   │   │   │   ├── app_adapter.py
│   │   │   │   ├── db_cache.py
│   │   │   │   ├── file_cache.py
│   │   │   │   ├── integrated.py
│   │   │   │   ├── mongodb_cache_adapter.py
│   │   │   │   └── manager.py
│   │   │   ├── providers/        # 数据供应商
│   │   │   │   ├── base_provider.py
│   │   │   │   ├── us/           # 美股（yfinance, Alpha Vantage, Finnhub）
│   │   │   │   ├── hk/           # 港股
│   │   │   │   ├── china/        # A股（AKShare, Baostock, Tushare）
│   │   │   │   └── examples/
│   │   │   ├── news/             # 新闻获取
│   │   │   │   ├── google_news.py
│   │   │   │   ├── realtime_news.py
│   │   │   │   ├── reddit.py
│   │   │   │   └── chinese_finance.py
│   │   │   ├── technical/        # 技术指标
│   │   │   ├── stock_data_service.py
│   │   │   └── ...
│   │   ├── graph/                # LangGraph 图编排
│   │   │   ├── trading_graph.py  # 主图（~1100行）
│   │   │   ├── setup.py
│   │   │   ├── propagation.py
│   │   │   ├── reflection.py
│   │   │   ├── signal_processing.py
│   │   │   └── conditional_logic.py
│   │   ├── llm_adapters/         # LLM 适配器
│   │   ├── llm_clients/          # LLM 客户端
│   │   ├── models/               # 数据模型
│   │   ├── tools/                # Agent 工具
│   │   └── utils/                # 工具函数
│   │
│   ├── agent_utils.py            # Agent 工具（策略信号查询）
│   ├── ai_analysis.py            # AI 分析主入口（集成 TradingAgents）
│   ├── quick_analysis.py         # 快速分析（单次 LLM 调用）
│   ├── chanlunx_algo.py          # ChanlunX C++移植版缠论算法
│   ├── eval_results/             # 策略回测结果
│   └── scripts/                  # 运维脚本
│       ├── daily_sync.py         # 每日数据同步
│       ├── data_update.py        # 数据增量更新
│       ├── batch_download.py     # 批量下载历史数据
│       ├── big_deal_collect.py   # 大单数据采集
│       ├── strategy_sync.py      # 策略同步
│       ├── health_check.py       # 健康检查
│       ├── refresh_vol20day.py   # 20日均量刷新
│       ├── fast_backfill.py      # 快速回填
│       └── 盘口异动_分类解析/     # 盘口异动 Excel 输出
│
├── frontend/                     # 🖥️ Vue 3 前端
│   ├── index.html               # HTML 入口（移动端适配）
│   ├── package.json             # 前端依赖（Vue 3, Vant, lightweight-charts）
│   ├── vite.config.js           # Vite 配置（代理 /api → 8765）
│   ├── dist/                    # 构建产物
│   │   └── assets/              # JS/CSS 打包
│   └── src/
│       ├── main.js              # Vue 入口
│       ├── App.vue              # 根组件 + 底部导航
│       ├── router/index.js      # 路由（9 个页面）+ 鉴权守卫
│       ├── utils/api.js         # Axios API 封装
│       └── views/
│           ├── Login.vue        # 登录页
│           ├── Home.vue         # 主页（搜索 + 大盘概览）
│           ├── Kline.vue        # K线图（lightweight-charts + 缠论叠加）
│           ├── Fundamentals.vue # 基本面详情页
│           ├── Screener.vue     # 选股筛选器
│           ├── Strategies.vue   # 量化策略看板
│           ├── Chanlun.vue      # 缠论分析页（4算法对比）
│           ├── Links.vue        # 外部链接聚合
│           └── Settings.vue     # 设置页面
│
├── chanlun-vendors/             # 📚 缠论第三方算法库
│   └── chanlun-pro/
│       └── orig_cl/             # 原始 cl.py 子进程调用
│
├── start.sh                     # 一键启动脚本（后端 8765 + 前端 3000）
├── daily_update.sh              # 每日数据更新脚本（crontab 部署）
├── reload_daily.py              # 日线数据重载工具
├── fill_stock_info.py           # 股票信息填充
├── fix_missing_0506.py          # 数据修复脚本
├── fix_volume_adj.py            # 复权修复脚本
└── fix_0506.log                 # 修复日志
```

---

## 二、技术栈清单

| 层级 | 技术 | 用途 |
|------|------|------|
| **后端框架** | Python 3.11+, FastAPI | API 服务器（异步 + 自动文档） |
| **服务网关** | uvicorn (asyncio) | ASGI 服务器 |
| **数据源** | **AKShare** (东方财富) | 主数据源：日线/分钟线/列表 |
| | **Baostock** | 备用数据源：前复权日线/交易日历 |
| | **Tushare** (基础积分) | 扩展基本面（受限） |
| | **yfinance** / Alpha Vantage / Finnhub | 美股数据 |
| **数据存储** | SQLite (WAL 模式) | 缓存层 + 选股结果 |
| | MongoDB (可选) | TradingAgents 存储后端 |
| **LLM 推理** | DeepSeek (默认) | 主力 LLM API |
| | OpenAI / 通义千问 / 智谱 GLM | 可选 LLM 供应商 |
| | LangChain / LangGraph | Agent 编排框架 |
| **前端** | Vue 3 (Composition API) | SPA 框架 |
| | Vite 8 | 构建工具 + 开发服务器 |
| | Vant 4 | 移动端 UI 组件库 |
| | lightweight-charts 5 | 专业 K 线图表（TradingView 同款） |
| | Vue Router 4 + Pinia 3 | 路由 + 状态管理 |
| | Axios | HTTP 客户端 |
| **量化策略** | 自研 Sequoia-X 引擎 | 6 种因子选股策略 |
| **缠论算法** | chanlun-pro (Python) | 标准缠论（笔/线段/中枢） |
| | ChanlunX (C++ 移植) | 通达信算法 Python 重写 |
| **运维** | Bash 脚本 (start.sh / daily_update.sh) | 启动 + 定时数据更新 |
| | cron (推测) | 每日收盘后自动同步 |

---

## 三、核心模块说明

### 3.1 数据获取与缓存层 (`backend/data/`)

```
AKShare ──┐
          ├──→ cache.py (SQLite) ──→ 前端 / API 响应
Baostock ─┘      ↑
           validator.py (双源交叉校验)
```

- **双源交叉校验**: 对日线级别数据，同时从 AKShare 和 Baostock 获取，对比开盘价/收盘价/最高价/最低价/成交量，差异超过阈值（2%-5%）的记录日志
- **缓存策略**: 优先使用缓存，检查新鲜度（max_days），过期则实时获取并回写
- **Sequoia Engine**: 独立数据引擎，管理 `stock_daily` 全量日线表，提供 baostock 增量同步

### 3.2 API 路由层 (`backend/routes/`)

| 路由前缀 | 模块 | 关键端点 |
|---------|------|---------|
| `/api/v1/kline/{symbol}` | kline | 获取K线（支持 daily/weekly/monthly/15min/30min/60min） |
| `/api/v1/stocks` | kline | A股列表 |
| `/api/v1/fundamentals/{symbol}` | kline | 基本面 |
| `/api/v1/screener` | kline | 选股筛选 |
| `/api/v1/bigbuy/{symbol}` | kline | 大单买入数据 |
| `/api/v1/strategy/*` | strategy | Sequoia-X 策略：状态/列表/同步/选股结果/个股信号 |
| `/api/v1/chanlun/*` | chanlun | 缠论分析：4算法对比、笔/线段/中枢/买卖点 |
| `/api/ai/quick` | ai | 快速分析（秒级） |
| `/api/ai/analyze` | ai | 深度分析（多 Agent） |
| `/api/ai/analyze/stream` | ai | 深度分析（SSE 流式推送进度） |
| `/api/auth/*` | auth | 登录/注册/分析缓存 |
| `/api/v1/favorites/*` | favorites | 自选股 CRUD |
| `/chanlun/*` | main.py | 反向代理至 chanlun-pro (端口 9900) |

### 3.3 Sequoia-X 量化选股引擎

**6 种选股策略**，运行在统一 `BaseStrategy` 框架下：

| 策略 | 算法思想 | 典型条件 |
|------|---------|---------|
| 均线放量 | 趋势跟进 | MA5 上穿 MA20 + 成交量 > 20日均量 × 1.5 |
| 海龟交易 | 通道突破 | 唐奇安通道（20日高点突破买入） |
| 高窄旗形 | 形态突破 | 价格窄幅整理后放量突破 |
| 涨停洗盘 | 资金博弈 | 涨停后缩量回调再放量 |
| 跌停反包 | 反转确认 | 上升趋势中跌停后次日反包 |
| RPS 突破 | 动量排序 | 120日 RPS > 90 分位 |

**工作流**:
1. DataEngine 从 baostock 拉取全市场日线 → `stock_daily` 表
2. 遍历各策略 → 返回选中股票列表 → 写入 `strategy_picks` 表
3. API / 前端查询选股结果

### 3.4 TradingAgents-CN 多 Agent 研判系统

基于 **LangGraph** 构建的多 Agent 流水线：

```
┌─────────────┐
│  数据收集    │  ← 基本面/新闻/社交媒体/市场环境/技术指标
└──────┬──────┘
       ↓
┌─────────────┐
│  分析师们    │  ← 基本面分析师、新闻分析师、市场分析师、社会情绪分析师
└──────┬──────┘
       ↓
┌─────────────┐
│  研究员辩论  │  ← 多头研究员 vs 空头研究员（辩论数轮）
└──────┬──────┘
       ↓
┌─────────────┐
│  风控辩论    │  ← 激进/保守/中立 三方面风控讨论
└──────┬──────┘
       ↓
┌─────────────┐
│  交易员决策  │  ← 综合所有信号，输出买入/卖出/持有 + 置信度
└─────────────┘
```

**支持**: 多 LLM 供应商切换、流式进度推送 (SSE)、中文输出、检查点恢复

### 3.5 缠论分析模块

提供 **4 套算法的缠论计算对比**：

1. **严格算法** (`CL` 默认) — 分型不包含
2. **宽松算法** (`CL` 配置) — 分型可包含，次高低成笔
3. **极严算法** (`CL` 配置) — 不允许次高低，严格成笔
4. **ChanlunX** — C++ 通达信插件算法 Python 移植

输出: 笔 (Bi)、线段 (XD)、中枢 (ZS)、买卖点信号

### 3.6 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| 登录 | `/login` | 用户名登录/注册 |
| 主页 | `/` | 股票搜索 + 大盘概览 |
| K线 | `/kline/:symbol` | 专业 K 线图 + 缠论叠加 + 技术指标 |
| 基本面 | `/fund/:symbol` | 公司详情/财务数据 |
| 选股器 | `/screener` | 市值/行业筛选 |
| 策略 | `/strategies` | 量化策略选股结果看板 |
| 缠论 | `/chanlun` | 缠论分析（4算法对比） |
| 链接 | `/links` | 外部工具链接聚合 |
| 设置 | `/settings` | 用户设置 |

---

## 四、数据流向图

```
                    ┌──────────────────────────────────────────────┐
                    │              前端 (Vue 3 + Vant)             │
                    │   localhost:3000 (dev) / dist (production)   │
                    │                                              │
                    │  [K线] [基本面] [策略] [缠论] [选股器] [AI]  │
                    └──────────────────┬───────────────────────────┘
                                       │ HTTP / Axios (Vite proxy /api → 8765)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            后端 (FastAPI :8765)                                   │
│                                                                                  │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐ ┌──────────────┐ │
│  │ Kline   │ │Strategy  │ │Chanlun  │ │AI      │ │Auth   │ │ Favorites    │ │
│  │ Router  │ │ Router   │ │ Router   │ │Router  │ │Router │ │ Router       │ │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬───┘ └───┬────┘ └──────┬───────┘ │
│       │           │            │            │         │             │          │
│       ▼           ▼            ▼            ▼                  ┌────┴────┐     │
│  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │ SQLite  │     │
│  │数据层  │ │ Sequoia-X│ │缠论库    │ │TradingAgents │       │ cache   │     │
│  │cache.py│ │ 引擎     │ │chanlun   │ │(LangGraph)  │       └─────────┘     │
│  │validator││ 6大策略  │ ├──────────┤ └──────┬───────┘                      │
│  └────┬───┘ └──────────┘ │ChanlunX │        │                              │
│       │                  └──────────┘        ▼                              │
│       ▼                                     ┌──────────────────┐            │
│  ┌─────────┐                                │  LLM 供应商      │            │
│  │ SQLite  │                                │ DeepSeek/OpenAI/ │            │
│  │ stock_  │                                │ 通义千问/智谱    │            │
│  │ cache.db│                                └──────────────────┘            │
│  └─────────┘                                                               │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────┐            │
│  │             数据供应商 (Data Providers)                      │            │
│  │  ┌─────────┐  ┌─────────┐  ┌────────┐  ┌────────────────┐ │            │
│  │  │AKShare  │  │Baostock │  │Tushare │  │yfinance / AV   │ │            │
│  │  │(主)     │  │(备)     │  │(扩展)  │  │(国际)          │ │            │
│  │  └─────────┘  └─────────┘  └────────┘  └────────────────┘ │            │
│  └─────────────────────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────────────────────┘


其他组件:
┌───────────────┐      ┌───────────────┐
│  chanlun-pro  │◄─────│  反向代理     │
│  (端口 9900)  │      │  /chanlun/*   │
└───────────────┘      └───────────────┘

┌────────────────┐     ┌──────────────────┐
│ Shell 启动脚本 │     │ 飞书 Webhook     │
│ start.sh       │     │ (策略通知)       │
│ daily_update.sh│     │                  │
└────────────────┘     └──────────────────┘
```

---

## 五、关键配置项

### 5.1 环境变量 (`.env`)

```ini
DEEPSEEK_API_KEY=sk-xxx                    # DeepSeek LLM 主 API Key
OPENAI_API_KEY=sk-xxx                       # OpenAI 可选
DASHSCOPE_API_KEY=sk-xxx                    # 通义千问可选
ZHIPU_API_KEY=xxx                           # 智谱可选
TUSHARE_TOKEN=xxx                           # Tushare Token
GOOGLE_API_KEY=xxx                          # Google API Key

# TradingAgents 开关
ONLINE_TOOLS_ENABLED=true                   # 在线工具
ONLINE_NEWS_ENABLED=true                    # 在线新闻
REALTIME_DATA_ENABLED=true                  # 实时数据
USE_MONGODB_STORAGE=false                   # MongoDB 存储（默认禁用）
DISABLE_CHROMADB=true                       # ChromaDB（默认禁用）

# 飞书 Webhook（策略通知）
FEISHU_WEBHOOK_URL=https://open.feishu.cn/...
STRATEGY_WEBHOOK_MA_VOLUME=...
STRATEGY_WEBHOOK_TURTLE_TRADE=...
```

### 5.2 后端配置 (`backend/config.py`)

```python
DB_PATH = BASE_DIR / "data" / "stock_cache.db"    # 主 SQLite 数据库
DATA_SOURCES = ["akshare", "baostock"]              # 数据源优先级
REQUEST_INTERVAL = 0.5                              # 请求间隔（防封）
VALIDATION_TOLERANCE = {
    "open": 0.02, "close": 0.02,                    # ±2%
    "high": 0.03, "low": 0.03,                      # ±3%
    "volume": 0.05,                                  # ±5%
}
```

### 5.3 前端 Vite 配置 (`frontend/vite.config.js`)

```javascript
server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: { '/api': { target: 'http://127.0.0.1:8765' } }
}
```

### 5.4 Sequoia-X 配置 (`backend/sequoia_x/core/config.py`)

- `db_path`: 默认 `data/sequoia_v2.db`
- `start_date`: 回测起始日期 `2024-01-01`
- `feishu_webhook_url`: 飞书通知（必填）
- `strategy_webhooks`: 各策略专属机器人 Webhook

### 5.5 TradingAgents 默认配置 (`backend/tradingagents/default_config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `llm_provider` | `openai` | 运行时覆盖为 `deepseek` |
| `deep_think_llm` | `deepseek-chat` | 深度推理模型 |
| `quick_think_llm` | `deepseek-chat` | 快速响应模型 |
| `max_debate_rounds` | 1 | 研究员辩论轮数 |
| `output_language` | `Chinese` | 中文输出 |

---

## 六、启动与运维

### 一键启动
```bash
./start.sh
# 后端 → http://localhost:8765/docs (API 文档)
# 前端 → http://localhost:3000
```

### 每日数据更新 (cron)
```bash
# 每日 17:30 执行（收盘后数据通常 17:00 就绪）
30 17 * * 1-5 /home/dogzi/.openclaw/workspace/a-stock-analyst/daily_update.sh
```

流程: 同步交易日历 → 判断交易日 → 检查 baostock 数据就绪 → 增量写入 `stock_daily` → 增量写入 `kline_cache`

### 服务端口
| 服务 | 端口 |
|------|------|
| FastAPI 后端 | 8765 |
| Vite 前端开发 | 3000 |
| chanlun-pro (第三方) | 9900 |

---

## 七、架构总结

```
┌──────────────────────────────────────────────────────────┐
│                    总体架构风格                           │
│            单体 Web 应用（前后端分离）                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  🖥️ 前端层    Vue 3 SPA + Vant 移动端适配               │
│      ↓ HTTP / Axios (JSON + SSE 流式)                    │
│  📡 路由层    FastAPI 6 个路由模块                       │
│      ↓ 函数调用                                          │
│  💾 数据层    多源数据获取 → 双源校验 → SQLite 缓存      │
│      ↓                                                  │
│  📊 分析层    技术指标 / 基本面 / AI多Agent / 量化策略   │
│      ↓ 子进程/进程内                                     │
│  🤖 算法库   chanlun-pro / ChanlunX / 外部 LLM API       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                    核心设计原则                           │
│  1. 数据双源校验：AKShare 主 + Baostock 备               │
│  2. 缓存优先：减少 API 调用，加速响应                    │
│  3. 模块化路由：每个路由文件对应一个业务域               │
│  4. 手机优先：前端 Vant 组件库全移动端适配               │
│  5. 多 Agent 研判：模拟人类分析师团队讨论流程            │
└──────────────────────────────────────────────────────────┘
```
