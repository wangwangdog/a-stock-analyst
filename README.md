# 📊 A-Stock Analyst

A 股数据分析 + AI 多 Agent 研判 Web 工具。胖磊 🦞 出品。

**v0.16b** — chanlun-pro 全量集成 + nginx 路由 + 数据库统一

---

## 最新更新 (v0.14 → v0.16b — 2026-06-28)

### 🏗️ 架构重构：chanlun-pro 全量集成
- **v0.15**：将 chanlun-pro 源码（591 文件）整合到 `chanlun-pro/` 目录，清除所有 `cl-vendors` 外部引用
- **v0.16**：统一路径到 `a-stock-analyst/chanlun-pro/`，cl-vendors 全量迁移完成，无外部依赖
- **v0.16b**：修复从缠论返回 K 线空白问题 + nginx 注入时点修正

### 🌐 nginx 网关层（替代 Python proxy）
- nginx 接管 9900 端口路由：
  - `/` → a-stock (`:9901`)
  - `/a-stock/` → a-stock (`:9901`)
  - `/tv/` → chanlun-pro (`:9903`)
- JS/CSS 带哈希 → immutable 永久缓存
- `index.html` → no-cache + Last-Modified
- 后端 GZip 压缩

### 🗄️ 数据库统一
- 产业链数据（chain.db，124MB，11张表）全量合并到主 DB `/mnt/disk990g/sqlite-data/chanlun_klines.sqlite`
- 包括：4586 公司 / 511 行业 / 17K 产品 / 110K 产品关系 / 130 国物质流数据（62 万条）
- chain.db 已删除，此后所有数据统一单库

### 🧩 侧边栏重构
- 3 Tab 布局：**大单 | 策略 | 新闻**
- 宽度：200px → **240px**
- 大单字体 +1 号
- 策略 Tab：盘前/盘中/多策略/初筛按钮 + 策略网格列表

### 🤖 新闻产业链图谱
- 点击新闻 → 右侧 frame 展开黑底双图谱（国内产业链 + 全球供应链）
- Agent 思考步骤逐条展示（分析主题→匹配公司→识别行业→关联全球→生成图谱）
- 白色分界线 + 虚线跨境桥梁边
- 知识驱动匹配（12 个话题分类 → 对应 A 股公司 + 国外实体）

### 🐛 修复
- RSS 新闻时间解析：Unix 秒级时间戳 → ISO 日期字符串，解决显示 1970 年问题

### 🧩 侧边栏重构：共享组件统一
- **Sidebar.vue** 提取为共享组件，Home 和 Kline 两页 100% 一致
- **宽度**：150px → 200px
- **搜索框**、**大单/新闻Tab**、**全量90D/近5/1/近10/1** 按钮、**RSS新闻列表** 完全复用

### 🔍 大单排名精确筛选
- `bigbuy-rank` API 新增 `exact` 参数
- **近5/1**：5天内**恰好**1天大单买入 → `HAVING 天数 = 1`
- **近10/1**：10天内**恰好**1天大单买入
- **全量90D**：90天内汇总降序排列
- 前/后端均已对齐：`exact=1` 参数透传

### 📰 RSS 新闻系统
- `backend/rss_fetcher.py` + `backend/routes/rss.py` 全新
- 数据源：HN + 东方财富，自动 15 分钟定时抓取
- 新闻列表显示于侧边栏新闻Tab（Home + Kline 两页均支持）
- 点击标题新标签页打开原文

### 🛡️ 浏览器缓存彻底解决
- `Clear-Site-Data: "cache"` 头，首次加载即清空浏览器缓存
- JS URL 注入时间戳 `?v=…`，彻底防缓存
- uvicorn 移除 ETag/Last-Modified 响应头
- `backend/main.py` 重写静态文件服务逻辑
- 页面标题版本号（v8→v9→v10→v11）可视觉确认

### 🔗 缠论跳转
- K线页股票代码/名称点击 → 新标签打开 `https://dogzi-ms-7d73.tailbc211b.ts.net/` 缠论主页

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

### 📊 量化选股（集成 Sequoia-X）
- 6 大内置策略：海龟 / 均线放量 / 高窄旗形 / 涨停洗盘 / 跌停反包 / RPS 突破
- 策略运行与选股结果可视化
- 多策略交叉热股整合
- 个股策略信号历史查询
- baostock 数据引擎，8 进程并行增量同步

### ⏰ 智能数据流水线
- **交易日自动判断**：所有定时任务（数据同步/盘口异动/大单汇总）自动识别交易日，非交易日跳过
- **盘口异动**：自动获取并解析 20 类盘口异动数据，去噪入库
- **全流程闭环**：数据获取 → 入库 → 汇总 → 分析，一键串联

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
│   │   ├── daily_sync.py         # Sequoia-X 日常数据同步+策略选股
│   │   ├── hzeveryday.py         # 大单数据汇总（补齐代码6位+剔除9开头）
│   │   ├── pkyd.py               # 盘口异动数据获取+解析+入库流水线
│   │   └── wsqllite.py           # Excel 盘口数据写入SQLite
│   │
│   ├── sequoia/
│   │   └── bridge.py             # Sequoia-X 桥接模块（API+策略运行）
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
| `GET` | `/api/v1/sequoia/status` | Sequoia-X 引擎状态 |
| `GET` | `/api/v1/sequoia/strategies` | Sequoia-X 策略列表 |
| `POST` | `/api/v1/sequoia/run/{key}` | 运行单个策略 |
| `POST` | `/api/v1/sequoia/run-all` | 运行全部策略 |
| `GET` | `/api/v1/sequoia/history` | 策略运行历史 |
| `GET` | `/api/v1/sequoia/signals/{symbol}` | 个股策略信号 |
| `GET` | `/api/v1/sequoia/results/{key}` | 策略最新选股 |
| `GET` | `/api/v1/sequoia/hot-stocks` | 多策略交叉热股 |
| `POST` | `/api/v1/sequoia/sync` | 数据增量同步 |
| `POST` | `/api/v1/sequoia/backfill` | 全市场数据回填 |

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

数据通过定时任务自动同步，**所有任务均自动判断交易日，非交易日直接跳过**。

### 一键全量定时任务

```bash
cd backend/scripts
python3 pkyd.py            # 盘口异动获取 → 自动入库 → 自动汇总到大单表
```

### 分步执行

```bash
cd backend/scripts
python3 daily_sync.py      # Sequoia-X 数据增量同步（含策略选股）
python3 pkyd.py             # 盘口异动数据获取+入库+汇总
```

### 单步执行

```bash
# 盘口异动 Excel 解析
python3 pkyd.py

# 写入数据库（pkyd.py 自动调用，也可单独跑）
python3 wsqllite.py

# 大单数据汇总
python3 hzeveryday.py
```

### 数据流水线（pkyd.py 执行流程）

```
AKShare 盘口异动(20类) → Excel 文件 → wsqllite.py 入库(stock_records) → hzeveryday.py 汇总(hzeveryday)
                                                                       ↓
                                                                 K线页+AI分析使用
```

数据处理规则：
- 股票代码不足6位自动补齐（`.zfill(6)`）
- 剔除9开头的股票
- 剔除名称含 `ST` 或 `退` 的股票

---

## 部署指南（Tailscale + systemd）

### 环境要求

| 依赖 | 版本 |
|---|---|
| Python | ≥ 3.12 |
| Node.js | ≥ 18 |
| Tailscale | 已安装并登录 |
| systemd | 用户级 service 支持（`loginctl show-user $USER | grep Linger=yes`） |

### 1. 安装依赖

```bash
# Python 依赖（已全局安装，无需 venv）
pip3 install fastapi uvicorn akshare baostock loguru langgraph langchain-core langchain-openai openai chromadb dashscope pandas requests python-dotenv pytz tqdm httpx yfinance stockstats sse-starlette

# 前端依赖
cd frontend && npm install
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 启动服务（开发调试）

```bash
bash start.sh
```

### 4. 配置开机自启（systemd 用户服务）

```bash
# 复制 service 文件到用户目录
mkdir -p ~/.config/systemd/user/

# 重新加载并启用
systemctl --user daemon-reload
systemctl --user enable a-stock-backend.service a-stock-frontend.service
systemctl --user start a-stock-backend.service a-stock-frontend.service
```

查看状态：

```bash
systemctl --user status a-stock-backend.service
systemctl --user status a-stock-frontend.service
```

### 5. Tailscale 远程访问

> ⚠️ 首次配置需先执行一次 sudo 设置 operator（之后不需要）：
> `sudo tailscale set --operator=$USER`

```bash
# 配置 Serve（内网 HTTPS，Tailscale 网络内可用）
tailscale serve --bg --https 443 http://127.0.0.1:3000

# 配置 Funnel（公网 HTTPS，互联网可访问）
tailscale funnel --bg 3000
```

**重要：前端 Vite 配置需允许外部 Host** — 已在 `frontend/vite.config.js` 中设置 `allowedHosts: true`，否则 Tailscale 域名请求会被 Vite 拦截返回 403。

**`frontend/vite.config.js` 示例：**

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    host: '0.0.0.0',
    allowedHosts: true,  // ← 必须添加
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      }
    }
  }
})
```

### 6. 访问方式

| 入口 | URL | 说明 |
|---|---|---|
| HTTPS（内网+公网） | `https://<machine-name>.tail<code>.ts.net` | MagicDNS + Funnel，自动 HTTPS |
| HTTP 直连 | `http://<tailscale-ip>:3000` | Tailscale 内网 IP |
| API 文档 | `https://<machine-name>.tail<code>.ts.net/docs` | FastAPI Swagger |
| 后端 API | `http://<tailscale-ip>:8765` | 可直接访问后端 |

### 7. 管理命令

```bash
# 查看 serve/funnel 状态
tailscale serve status

# 关闭 serve (保留内网访问)
tailscale serve --https=443 off

# 关闭 funnel (保留内网 HTTPS)
tailscale funnel --https=443 off

# 完全重置
tailscale funnel reset
```

---

## 许可

- `backend/tradingagents/` 目录代码来自 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)，遵循 Apache 2.0 许可证
- 其余代码为原创，保留所有权利


---

## 数据库（stock_cache.db）

所有数据存储在 `backend/data/stock_cache.db`（SQLite）。

### 核心表

#### stock_daily — 日K线（前复权）
**数据来源：** baostock（adjustflag=2，前复权），单日增量通过 sequoia engine 同步  
**数据量：** 2730010 条，4985 只股票  
**日期范围：** 2024-01-02 ~ 2026-05-07

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增ID |
| symbol | TEXT | 股票代码 |
| date | TEXT | 交易日期（YYYY-MM-DD） |
| open | REAL | 开盘价（前复权） |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | REAL | 成交量（股） |
| turnover | REAL | 成交额（元） |

#### big_deal_summary — 大笔买入统计
**数据来源：** 逐笔成交扫描（akshare tick），连续≤3笔买盘合并达阈值即为1次大笔买入  
**触发时间：** 交易日 15:05  
**分档阈值：** 5元↓/5~10/10~50/50~100/100~500/500↑ → 50000/25000/15000/6000/3000/1000手  
**剔除规则：** 开盘 09:30 前、尾盘 15:00 后不计入  
**数据量：** 4939 条/日

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | TEXT | 交易日期 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| big_buy_count | INTEGER | 大笔买入次数 |
| big_buy_lots | REAL | 大笔买入总手数 |
| big_buy_amount | REAL | 大笔买入总金额（元） |
| total_lots | REAL | 全日总成交手数 |
| total_amount | REAL | 全日总成交金额（元） |

#### big_buy_summary — 有大买盘记录
**数据来源：** 盘口异动（akshare `stock_changes_em` 的"有大买盘"分类）  
**触发时间：** 交易日 17:30（随 pkyd.py）  
**数据量：** 7944 条

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增ID |
| trade_date | TEXT | 交易日期 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| time | TEXT | 发生时间（HH:MM:SS） |
| qty | REAL | 买入数量（股） |
| price | REAL | 成交单价（元） |
| change | REAL | 涨跌幅 |
| amount | REAL | 成交金额（元） |

#### hzeveryday — 大笔买入汇总
**数据来源：** 盘口异动→大笔买入分类，经 `wsqllite.py` → `hzeveryday.py` 汇总  
**数据量：** 5366 条

| 字段 | 类型 | 说明 |
|------|------|------|
| 股票代码 | TEXT | 股票代码 |
| 股票名称 | TEXT | 股票名称 |
| 大笔买数 | INTEGER | 大笔买入次数 |
| 合计金额 | REAL | 合计金额（元） |
| 合计手数 | REAL | 合计手数 |
| 买入日期 | TEXT | 交易日期 |

#### all_stock_info — 全市场股票基本信息
**数据来源：** akshare（代码名称）+ stock_individual_info_em（市值）+ baostock（每股收益）  
**数据量：** 4939 只

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| market_cap | REAL | 总市值 |
| eps | REAL | 每股收益（最新季度） |
| pe_ratio | REAL | 市盈率 |
| industry | TEXT | 行业 |
| listing_date | TEXT | 上市日期 |
| updated_at | TEXT | 更新时间 |

#### trade_calendar — A股交易日历
**数据来源：** baostock  
**数据量：** 1096 天

| 字段 | 类型 | 说明 |
|------|------|------|
| calendar_date | TEXT | 日历日期（YYYY-MM-DD） |
| is_trading_day | INTEGER | 是否交易日（1=是，0=否） |


#### all_stcok_daydeal — 全市场非小单逐笔成交
**数据来源：** akShare 逐笔成交（stock_zh_a_tick_tx_js），与 big_deal_summary 同时采集  
**触发时间：** 交易日 15:05（随 big_deal_collect.py）  
**小单排除规则：** 5元↓/<5000手、5~10/<3000、10~50/<2000、50~100/<500、100~500/<200、500↑/<50手视为小单不记入

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增ID |
| trade_date | TEXT | 交易日期 |
| symbol | TEXT | 股票代码 |
| time | TEXT | 发生时间（HH:MM:SS） |
| price | REAL | 成交价格（元） |
| qty | REAL | 成交量（手） |
| amount | REAL | 成交金额（元） |
| direction | TEXT | 买卖方向（买盘/卖盘/中性盘） |

### 定时任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 15:05 | big_deal_summary | 逐笔成交大笔买入扫描 |
| 17:30 | a-stock-abnormal-update | sequoia 数据同步 + 策略 |
| 17:30 | a-stock-daily-update | kline_cache 增量更新 |
| 17:30 | a-stock-pkyd | 盘口异动全流程 + 有大买盘入库 |
