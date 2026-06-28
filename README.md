# 📊 A-Stock Analyst

A 股数据分析 + 产业链知识图谱 Web 工具。胖磊 🦞 出品。

**v0.17** — Tavily 新闻源 + 异步分析队列 + 数据库全量统一 + 关键词产业链匹配

---

## 最新更新 (v0.16b → v0.17 — 2026-06-28)

### 📰 新闻源扩展
- **新增 Tavily 财经新闻源**：通过 Tavily API 搜索 A 股/行业/科技/板块热点，写入统一新闻表
- **5 个新闻源，独立更新频率**：

| 源 | 类型 | 更新间隔 |
|------|------|---------|
| TrendRadar 热点 | RSS | 15 分钟 |
| Buzzing HN | RSS | 15 分钟 |
| Buzzing ProductHunt | RSS | 15 分钟 |
| 36氪 科技财经 | RSS | 15 分钟 |
| Tavily 财经 | API（Tavily Search） | **60 分钟** |

- 三去重管道（URL → 标题精确 → 标题模糊），跨源去重

### 🔗 新闻→产业链图谱
- **纯关键词匹配**（FOREIGN_MAP + CN_TOPIC_MAP + 数据库模糊搜索），无 LLM 依赖
- 点击新闻 → 12ms 秒出双图谱（国内产业链 + 全球供应链）
- 无匹配时不兜底，返回空图谱
- G6 v5 图谱：黑底 + 桥接线 + 可编辑（右键菜单 + 搜索添加节点）
- 双击公司节点 → 调 `/api/v1/chain/expand-smart` 展开产业链（纯 DB 查询）

### 🗄️ 数据库全量统一
- 唯一 DB：`/mnt/disk990g/sqlite-data/chanlun_klines.sqlite`（~26GB）
- 产业链数据：11 张表（4586 公司 / 511 行业 / 17K 产品 / 110K 产品关系 / 62 万条物质流数据）
- 删除 `backend/data/chain.db`，历史 `stock_cache.db` 已归档

### 🧹 其他
- 删除所有本地 Ollama 调用（qwen3:30b → 不存在，后端改用纯关键词匹配）
- 删除「新闻产业链分析」定时 cron job（改为点击时直接响应）
- 更新 SOURCE_NAMES 映射，前端正确显示各源名称

---

## 功能一览

### 📈 K 线分析
- 日K/周K/月K/60分/30分/15分
- MA / MACD / RSI / 布林带 / KDJ
- 大单买入量 + 大单买入比例子图
- 最近7日高低点连线标记

### 📰 新闻聚合
- 5 个新闻源（RSS + Tavily API），自动定时抓取
- 三去重管道，跨源去重
- 侧边栏新闻 Tab 列表，时间/来源标记
- 点击新闻 → 产业链图谱展开

### 🗺️ 产业链图谱
- 新闻→实体匹配（关键词 + DB）
- 双图谱展示：国内产业链 + 全球供应链
- 公司/行业/产品/材料/下游分类节点
- 可编辑：右键添加/删除节点，搜索添加
- 双击展开深层次产业链关系

### 📊 量化选股（集成 Sequoia-X）
- 6 大内置策略：海龟 / 均线放量 / 高窄旗形 / 涨停洗盘 / 跌停反包 / RPS 突破
- 策略运行与选股结果可视化
- 多策略交叉热股整合
- 个股策略信号历史查询

### ⏰ 智能数据流水线
- **交易日自动判断**：所有定时任务自动识别交易日，非交易日跳过
- 大单买入扫描（15:05）
- 盘口异动全流程（17:30）
- RSS 新闻抓取（每 15 分钟）
- Tavily 新闻抓取（每 60 分钟）

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

---

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/login` | 登录/注册 |
| `GET` | `/api/auth/me` | 获取当前用户 |
| `GET` | `/api/v1/kline/{symbol}` | K线数据 |
| `GET` | `/api/v1/bigbuy/{symbol}` | 大单买入数据 |
| `GET` | `/api/v1/bigbuy-rank` | 大单买入天数排名(前200) |
| `GET` `/POST` `/DELETE` | `/api/v1/favorites` | 自选股管理 |
| `POST` | `/api/ai/quick` | ⚡ 快速分析 |
| `POST` | `/api/ai/analyze` | 🧠 深度分析 |
| `GET` | `/rss-api/list` | 新闻列表 |
| `GET` | `/rss-api/sources` | 新闻源列表 |
| `POST` | `/rss-api/fetch` | 触发 RSS 抓取 |
| `GET` | `/api/v1/chain/stock/{code}` | 个股产业链数据 |
| `GET` | `/api/v1/chain/search` | 搜索公司/产品/行业 |
| `GET` | `/api/v1/chain/news-supply-chain` | 新闻→产业链图谱 |
| `POST` | `/api/v1/chain/news-request` | 提交新闻分析请求 |
| `GET` | `/api/v1/chain/news-request/{id}` | 查询分析结果 |

---

## 数据库 (`/mnt/disk990g/sqlite-data/chanlun_klines.sqlite`)

**唯一数据库**，约 26GB。包含 K 线数据、产业链数据、新闻数据。

### 核心表

#### kline_cache — K 线数据缓存
**数据来源：** AKShare / BaoStock / Tencent 多源合并  
**数据量：** 数百万条，覆盖全 A 股

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | TEXT | 股票全码（SH/SZ/BJ.XXXXXX） |
| trade_date | TEXT | 交易日期（YYYY-MM-DD） |
| period | TEXT | 周期（daily/weekly/monthly/5m/15m/30m/60m） |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | REAL | 成交量（日线=手数，分钟线=股数） |
| amount | REAL | 成交额（元） |
| source | TEXT | 数据源标识 |

#### big_deal_summary — 大笔买入统计
**数据来源：** 逐笔成交扫描（akshare tick），连续≤3笔买盘合并达阈值即为1次大笔买入  
**触发时间：** 交易日 15:05

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | TEXT | 股票代码 |
| trade_date | TEXT | 交易日期 |
| name | TEXT | 股票名称 |
| buy_amount | REAL | 买入金额 |
| sell_amount | REAL | 卖出金额 |
| net_amount | REAL | 净买入金额 |

#### rss_news_dedup — 去重新闻（三去重后）
**数据来源：** RSS 源 + Tavily API  
**数据量：** 持续增长

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | MD5 内容 ID |
| source | TEXT | 源标识（trendradar/buzzing_hn/buzzing_ph/kr36/tavily） |
| source_name | TEXT | 源显示名 |
| title | TEXT | 新闻标题 |
| link | TEXT | 原文链接 |
| summary | TEXT | 摘要 |
| published | TEXT | 发布时间 |
| fetched_at | REAL | 抓取时间（Unix 时间戳） |

#### rss_fetch_state — 抓取状态
| 字段 | 类型 | 说明 |
|------|------|------|
| source | TEXT | 源标识 |
| last_fetched_at | REAL | 上次抓取时间 |
| last_article_time | TEXT | 最新文章时间 |

#### chain_companies — 产业链公司库
**数据量：** 4586 公司

| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 股票代码 |
| name | TEXT | 公司名称 |
| fullname | TEXT | 公司全称 |
| location | TEXT | 所在地 |
| list_time | TEXT | 上市日期 |

#### chain_company_industry — 公司所属行业
| 字段 | 类型 | 说明 |
|------|------|------|
| company_code | TEXT | 公司代码 |
| company_name | TEXT | 公司名称 |
| industry_code | TEXT | 行业代码 |
| industry_name | TEXT | 行业名称 |

#### chain_company_product — 公司主营产品
| 字段 | 类型 | 说明 |
|------|------|------|
| company_code | TEXT | 公司代码 |
| company_name | TEXT | 公司名称 |
| product_name | TEXT | 产品名称 |
| rel | TEXT | 关系类型 |

#### chain_product_relation — 产品上下游关系
**数据量：** 110K+ 条

| 字段 | 类型 | 说明 |
|------|------|------|
| from_entity | TEXT | 上游/源产品 |
| to_entity | TEXT | 下游/目标产品 |
| rel | TEXT | 关系（上游材料/下游产品/产品小类） |

#### chain_same_industry — 同行业公司
| 字段 | 类型 | 说明 |
|------|------|------|
| company_code | TEXT | 公司代码 |
| company_name | TEXT | 公司名称 |
| peer_code | TEXT | 同行公司代码 |
| peer_name | TEXT | 同行公司名称 |
| industry_name | TEXT | 行业名称 |

#### news_analysis_queue — 新闻分析异步队列
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 任务ID（UUID前8位） |
| title | TEXT | 新闻标题 |
| summary | TEXT | 新闻摘要 |
| status | TEXT | 状态（pending/done/error） |
| result | TEXT | 分析结果（JSON） |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

### 定时任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 每 15 分钟 | RSS 新闻抓取 + 三去重 | 抓取 4 个 RSS 源 |
| 每 60 分钟 | Tavily 新闻抓取 + 三去重 | Tavily API 搜索财经新闻 |
| 15:05 | 大单买入扫描 | 逐笔成交大笔买入扫描 |
| 17:30 | 盘口异动全流程 | 盘口异动获取+入库+汇总 |
| 17:30 | 数据同步+策略 | sequoia 数据同步 + 策略选股 |

---

## 目录结构

```
a-stock-analyst/
├── README.md
├── .env.example                 # API Key 配置模板
│
├── backend/                     # FastAPI 后端
│   ├── main.py                  # 主入口 + 静态文件服务
│   ├── config.py                # 配置
│   ├── ai_analysis.py           # 多 Agent 深度分析
│   ├── quick_analysis.py        # 快速分析（单次 LLM）
│   │
│   ├── data/                    # 数据层
│   │   ├── cache.py             # SQLite 缓存
│   │   ├── chain_import.py      # 产业链数据导入
│   │   └── download_provider.py # 多源数据下载
│   │
│   ├── routes/                  # API 路由
│   │   ├── kline.py             # K线/大单/筛选
│   │   ├── chain.py             # 产业链查询 + 新闻图谱
│   │   ├── rss.py               # RSS 新闻 API
│   │   ├── ai.py                # AI 分析
│   │   ├── strategy.py          # 量化策略
│   │   └── auth.py              # 登录/缓存
│   │
│   ├── scripts/                 # 定时任务脚本
│   │   ├── cron_news_fetch.sh   # RSS 新闻抓取（15min）
│   │   ├── daily_sync.py        # 数据同步 + 策略选股
│   │   ├── pkyd.py              # 盘口异动全流程
│   │   └── hzeveryday.py        # 大单数据汇总
│   │
│   ├── sequoia_x/               # Sequoia-X 量化引擎
│   │   ├── strategy/            # 6 大内置策略
│   │   └── core/                # 引擎核心
│   │
│   └── tradingagents/           # TradingAgents-CN 多 Agent 研判
│
├── chanlun-pro/                 # 缠论分析引擎（全量集成）
│   ├── web/chanlun_chart/       # 缠论 Web 服务（9903 端口）
│   │   └── cl_app/
│   │       ├── rss_fetcher.py   # RSS 三去重抓取
│   │       └── tavily_fetcher.py# Tavily API 新闻抓取
│   ├── orig_cl/                 # 缠论核心算法
│   └── .venv/                   # Python 虚拟环境
│
├── frontend/                    # Vue3 前端
│   ├── src/
│   │   ├── components/
│   │   │   ├── Sidebar.vue      # 侧边栏（大单/策略/新闻 Tab）
│   │   │   ├── NewsChainPanel.vue # 新闻产业链图谱面板
│   │   │   └── TupuPanel.vue    # 产业链图谱组件
│   │   ├── views/
│   │   │   ├── Home.vue         # 主页
│   │   │   ├── Kline.vue        # K线分析页
│   │   │   └── ...              # 其他页面
│   │   └── router/index.js      # 路由
│   └── dist/                    # 构建产出
│
├── data/                        # 数据文件
│   └── chain_knowledge/         # 产业链原始数据
│
├── deploy/                      # 部署脚本
│   └── hermes-scripts/          # Hermes cron job 脚本
│
├── scripts/                     # 工具脚本
├── veighna_integration/         # VeighNa 集成
└── vnpy_chanlun/               # vnpy 缠论适配
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python FastAPI + Uvicorn |
| 前端 | Vue3 + Vant 4 + lightweight-charts |
| 图谱 | @antv/g6 v5 |
| 新闻 | Tavily API + feedparser |
| 数据源 | AKShare + BaoStock + Tencent |
| 缓存 | SQLite (本地) |
| 部署 | nginx 反向代理（Tailscale） |

---

## 许可

- `backend/tradingagents/` 目录代码来自 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)，遵循 Apache 2.0 许可证
- 其余代码为原创，保留所有权利
