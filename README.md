# 📊 A-Stock Analyst

A 股数据分析 + AI 多 Agent 研判 Web 工具。胖磊 🦞 出品。

---

## 功能一览

### 📈 K 线分析
- 日K/周K/月K/60分/30分/15分
- MA / MACD / RSI / 布林带 / KDJ
- 大单买入量 + 大单买入比例子图
- 最近7日高低点连线标记

### 🤖 AI 多 Agent 研判（集成 TradingAgents-CN）
- **⚡ 快速分析**（秒级）：主力资金介入判断 + 底部形态识别
- **🧠 深度分析**（3-5分钟）：10+ Agent 完整流水线
  - 基本面分析师 · 技术分析师 · 情绪分析师 · 新闻分析师
  - 多头/空头研究员辩论 → 交易员决策 → 风控审核
  - 三栏展示：基本面分析 / 多头观点 / 空头观点

### 📋 选股与自选
- 按行业/市值筛选
- 自选股数据库化存储（每人独立）
- 大笔买入天数排名侧栏（剔除9开头和ST股）

### 🔐 多用户登录
- 用户名自动注册
- 每人独立自选股 + 分析结果缓存（24h免重复调用）

---

## 快速启动

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 启动
cd a-stock-analyst
bash start.sh

# 3. 打开浏览器
# http://localhost:3000
```

## 环境要求

| 依赖 | 版本 |
|---|---|
| Python | ≥ 3.12 |
| Node.js | ≥ 18 |
| 内存 | ≥ 8GB（推荐 16GB） |
| 存储 | ≥ 10GB |

### Python 依赖
```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn akshare baostock loguru langgraph langchain-core langchain-openai openai chromadb dashscope pandas requests python-dotenv pytz tqdm httpx yfinance stockstats sse-starlette
```

---

## 完整目录结构

```
a-stock-analyst/
├── .env.example              # API Key 配置模板
├── start.sh                  # 一键启动脚本
├── README.md
│
├── backend/
│   ├── main.py               # FastAPI 主入口
│   ├── config.py             # 配置
│   ├── ai_analysis.py        # 多 Agent 深度分析集成入口
│   ├── quick_analysis.py     # 快速分析（单次 LLM 调用）
│   │
│   ├── data/
│   │   ├── akshare_fetcher.py    # AKShare 数据源（日/周/月/分钟K线）
│   │   ├── baostock_fetcher.py   # BaoStock 数据源（备用）
│   │   ├── cache.py              # SQLite 缓存
│   │   └── validator.py          # 双源交叉校验
│   │
│   ├── analysis/
│   │   ├── indicators.py         # 技术指标计算
│   │   └── fundamentals.py       # 基本面分析
│   │
│   ├── routes/
│   │   ├── kline.py              # K线/大单/筛选 API
│   │   ├── ai.py                 # 快速分析 + 深度分析(含流式SSE) API
│   │   ├── auth.py               # 登录 + 分析缓存 API
│   │   └── favorites.py          # 自选股 CRUD API
│   │
│   ├── scripts/
│   │   ├── hzeveryday.py         # 大单数据汇总（补齐代码6位+剔除9开头）
│   │   └── pkyd.py               # 定时任务入口
│   │
│   └── tradingagents/            # TradingAgents-CN 多 Agent 核心 (Apache 2.0)
│       ├── agents/               # 各分析师 Agent 实现
│       │   ├── analysts/         # 市场/基本面/新闻/社交媒体分析师
│       │   ├── researchers/      # 多头/空头研究员
│       │   ├── trader/           # 交易员
│       │   └── risk_mgmt/        # 风控团队
│       ├── graph/                # LangGraph 编排
│       └── dataflows/            # 数据接口（适配 A 股数据源）
│
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── Login.vue         # 登录页
│   │   │   ├── Home.vue          # 主页（左侧大单排名 + 右侧内容）
│   │   │   ├── Kline.vue         # K线页（含左侧栏 + AI分析）
│   │   │   ├── Fundamentals.vue  # 基本面页
│   │   │   └── Screener.vue      # 选股筛选页
│   │   ├── router/index.js       # 路由（含登录守卫）
│   │   ├── utils/api.js          # API 客户端
│   │   └── App.vue
│   └── package.json
│
└── memory/                      # 运行记录（胖磊的工作日志）
```

---

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/login` | 登录/注册 |
| `GET` | `/api/auth/me` | 获取当前用户 |
| `POST` | `/api/auth/cache/check` | 检查分析缓存(24h) |
| `POST` | `/api/auth/cache/save` | 保存分析结果 |
| `GET` | `/api/v1/kline/{symbol}` | K线数据 |
| `GET` | `/api/v1/bigbuy/{symbol}` | 大单买入数据 |
| `GET` | `/api/v1/bigbuy-rank` | 大单买入天数排名(前200) |
| `GET` | `/api/v1/fundamentals/{symbol}` | 基本面数据 |
| `GET` | `/api/v1/screener` | 选股筛选 |
| `GET` `/POST` `/DELETE` | `/api/v1/favorites` | 自选股管理 |
| `POST` | `/api/ai/quick` | ⚡ 快速分析 |
| `POST` | `/api/ai/analyze` | 🧠 深度分析 |
| `POST` | `/api/ai/analyze/stream` | 🧠 深度分析(SSE流式进度) |

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python FastAPI + Uvicorn |
| 前端 | Vue3 + Vant 4 + lightweight-charts |
| AI 框架 | LangGraph + LangChain |
| LLM | DeepSeek / OpenAI / Qwen / GLM |
| 数据源 | AKShare + BaoStock |
| 缓存 | SQLite (本地) |
| 部署 | Docker (可选) |

---

## 数据更新

数据通过定时任务自动同步，每交易日采集大单买入数据到 `hzeveryday` 表：

```bash
cd backend/scripts
python3 hzeveryday.py     # 汇总大单数据
python3 pkyd.py            # 全量定时任务
```

数据处理规则：
- 股票代码不足6位自动补齐（`.zfill(6)`）
- 剔除9开头的股票
- 剔除名称含 `ST` 或 `退` 的股票

---

## 许可

- `backend/tradingagents/` 目录代码来自 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)，遵循 Apache 2.0 许可证
- 其余代码为原创，保留所有权利
