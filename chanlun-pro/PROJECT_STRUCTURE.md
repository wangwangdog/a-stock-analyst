# AI缠论量化工具 - 融合架构文档

> 生成日期: 2026-05-09
> 基于 chanlun-pro (yijixiuxin) + a-stock-analyst (胖磊 🦞) 融合
> 部署路径: `/home/dogzi/.openclaw/workspace/cl-vendors/chanlun-pro/`

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Tailscale Funnel                        │
│              https://dogzi-ms-7d73.tailbc211b.ts.net          │
└─────────────────────────┬───────────────────────────────────┘
                          │ :443
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    chanlun-pro (Flask + Tornado)             │
│                          :9900                               │
│                                                             │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ TradingView   │  │ 缠论API   │  │ A-Stock Proxy + SPA  │  │
│  │ 缠论图表      │  │ /tv/*    │  │ /api/* ──► :9901    │  │
│  │ (Jinja2)     │  │          │  │ /a-stock/ (Vue3 SPA) │  │
│  └──────────────┘  └──────────┘  └──────────┬───────────┘  │
│                                              │              │
└──────────────────────────────────────────────┼──────────────┘
                                               │ Flask Proxy
                                               ▼
┌─────────────────────────────────────────────────────────────┐
│                a-stock-backend (FastAPI + Uvicorn)           │
│                          :9901                               │
│                                                             │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ K线/指标   │  │  AI多Agent    │  │  量化选股          │   │
│  │ /api/v1/*  │  │  /api/ai/*   │  │  /api/v1/strategy/*│   │
│  └────────────┘  └──────────────┘  └────────────────────┘   │
│                                                             │
│  ┌────────────────────┐  ┌──────────────────────────────┐   │
│  │ TradingAgents-CN   │  │  Sequoia-X 6大策略           │   │
│  │ 多Agent研判引擎    │  │  量化选股引擎                 │   │
│  └────────────────────┘  └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  共享数据库             │
              │  ~/.chanlun_pro/db/    │
              │  chanlun_klines.sqlite │
              │  38张表 / 716万行      │
              │  1.35 GB              │
              └───────────────────────┘
```

## 二、技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| **运行时** | Python 3.11 (uv 管理) | 后端服务 |
| **前端 A** | Vue3 + Vite + Vant 4 + lightweight-charts | A-Stock 传统K线分析 |
| **前端 B** | Jinja2 + TradingView Charting Library | 缠论图表展示 |
| **前端 C** | 原生 JS + LayUI + jQuery | 缠论后台管理页面 |
| **主服务** | Flask + Tornado (WSGI) | chanlun-pro :9900 |
| **副服务** | FastAPI + Uvicorn | a-stock-backend :9901 |
| **缠论引擎** | PyArmor 加密 (cl.py) | 逐Bar增量计算缠论数据 |
| **AI引擎** | LangGraph + LangChain | TradingAgents-CN 多Agent |
| **量化选股** | 纯 Python (Sequoia-X) | 6大策略 + 全A扫描 |
| **数据源** | AKShare + Baostock + TDX | 日/周/月/分钟K线 |
| **存储** | SQLite (WAL模式) | 合并数据库 |
| **缓存** | SQLite + pickle 序列化 | 缠论计算结果缓存 |
| **Agent记忆** | MongoDB (可选) | 会话/消息存储 |
| **反向代理** | Tailscale Funnel | 外网暴露 9900 端口 |

## 三、核心模块

### 3.1 缠论引擎（chanlun-pro 核心）

```
src/chanlun/
├── cl.py                  # PyArmor 加密缠论计算核心
├── cl_interface.py        # 接口定义 (FX/BI/XD/ZS/LINE 等)
├── cl_utils.py            # 工具函数 + TV 图表数据转换
├── cl_analyse.py          # 缠论分析辅助
├── file_db.py             # 文件缓存 (pickle 序列化)
├── config.py              # 服务配置
├── db.py                  # 数据库操作
├── exchange/              # 20+ 数据源适配器
│   ├── exchange_tdx.py    # 通达信 A股主数据源
│   ├── exchange_baostock.py
│   ├── exchange_binance.py
│   ├── exchange_futu.py
│   └── ...
├── backtesting/           # 回测框架
│   ├── backtest.py        # 回测引擎
│   ├── backtest_trader.py # 回测交易
│   └── optimize.py        # 参数优化
├── strategy/              # 缠论策略 (15+)
│   ├── strategy_xd_mmd.py
│   ├── strategy_zs_tupo.py
│   └── ...
├── trader/                # 实盘交易
│   ├── trader_a_stock.py
│   ├── trader_ctp.py
│   └── ...
├── tools/                 # AI辅助工具
│   ├── ai_analyse.py
│   └── ai_client.py
└── utils/
    └── trading_calendar.py # 交易日历 (AKShare)
```

**关键特性：**
- 逐Bar增量计算，新K线增量计算不重算历史
- 可缓存计算结果到 `.pkl` 文件
- 支持多市场（A股/港股/美股/期货/外汇/数字货币）
- 15+ 内置缠论交易策略
- 支持掘金、VNPY、WTPY 量化平台集成

### 3.2 A-Stock 后端（FastAPI :9901）

```
a_stock_backend/
├── main.py                # FastAPI 入口 (uvicorn :9901)
├── config.py              # 数据库配置 (指向合并库)
├── routes/
│   ├── kline.py           # K线/大单/筛选 API
│   ├── ai.py              # AI Agent 分析 API
│   ├── auth.py            # 登录/缓存 API
│   ├── favorites.py       # 自选股 CRUD
│   ├── strategy.py        # 量化选股策略 API
│   ├── chanlun.py         # 缠论数据 API
│   └── quant.py           # 快捷选股 API
├── data/
│   ├── cache.py           # SQLite 缓存层
│   ├── akshare_fetcher.py # AKShare 数据获取
│   ├── baostock_fetcher.py# BaoStock 数据获取
│   └── sequoia_engine.py  # Sequoia 策略调度引擎
├── tradingagents/         # 多 Agent 研判系统
│   ├── graph/             # LangGraph 编排
│   │   ├── trading_graph.py    # 主图定义
│   │   ├── propagation.py      # 信息传播
│   │   ├── reflection.py       # 反思机制
│   │   └── signal_processing.py# 信号处理
│   ├── agents/            # 各角色 Agent
│   │   ├── analysts/      # 分析师 (市场/基本面/新闻/社交媒体)
│   │   ├── researchers/   # 研究员 (多头/空头)
│   │   ├── trader/        # 交易员
│   │   ├── managers/      # 研究/风控经理
│   │   └── risk_mgmt/     # 风控辩论 (激进/保守/中立)
│   ├── llm_clients/       # LLM 适配器
│   │   ├── openai_client.py
│   │   ├── anthropic_client.py
│   │   ├── google_client.py
│   │   └── factory.py     # 工厂模式
│   ├── dataflows/         # 数据流 (A股/HK/美股/新闻)
│   └── config/            # 配置管理
├── sequoia_x/             # 量化选股引擎
│   ├── strategy/
│   │   ├── turtle_trade.py    # 海龟交易法则
│   │   ├── ma_volume.py       # 均线放量
│   │   ├── high_tight_flag.py # 高窄旗形
│   │   ├── limit_up_shakeout.py# 涨停洗盘
│   │   ├── uptrend_limit_down.py# 跌停反包
│   │   └── rps_breakout.py    # RPS 突破
│   └── core/
│       ├── config.py      # 引擎配置
│       └── engine.py      # 策略调度
├── scripts/               # 数据脚本
│   ├── daily_sync.py      # Sequoia 日常同步
│   ├── pkyd.py            # 盘口异动获取解析
│   ├── hzeveryday.py      # 大单数据汇总
│   └── ...
├── analysis/              # 分析工具
│   ├── indicators.py      # 技术指标
│   └── fundamentals.py    # 基本面
└── monitor/               # 监测模块
```

### 3.3 前端模块

```
web/chanlun_chart/
├── app.py                 # Flask + Tornado 入口
├── cl_app/
│   ├── __init__.py        # 路由定义 + create_app
│   ├── alert_tasks.py     # 监控定时任务
│   ├── other_tasks.py
│   ├── templates/         # Jinja2 模板
│   │   ├── index.html     # 缠论主页
│   │   ├── login.html     # 登录页
│   │   ├── dark.html      # 暗色主题
│   │   └── ...
│   └── static/
│       ├── a-stock/       # 🆕 A-Stock Vue3 前端
│       │   ├── index.html
│       │   └── assets/
│       ├── charting_library/ # TradingView 图表库
│       ├── datafeeds/     # UDF 数据源
│       ├── js/            # 前端逻辑
│       │   ├── charts.js  # 缠论绘图核心
│       │   └── bundle.js  # UDF 数据源
│       └── css/
```

## 四、数据流

### 4.1 K线数据流

```
AKShare/Baostock ──► kline_cache (每日增量)
                          │
                          ▼
                  stock_daily (前复权全量 276万行)
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                  ▼
  TradingView API      FastAPI K线          Sequoia 策略
  /tv/history          /api/v1/kline       选股计算
  (chanlun-pro)        (a-stock-backend)
```

### 4.2 缠论分析流

```
K线数据 ──► cl.py (PyArmor) ──► 缠论对象 (FX/BI/XD/ZS)
              │                         │
              ▼                         ▼
        pickle 缓存 (.pkl)       cl_utils.py → TV chart 数据
                                    │
                                    ▼
                              /tv/history API
                                    │
                                    ▼
                           charts.js → TradingView 绘图
```

### 4.3 AI 多 Agent 流

```
用户请求 ──► /api/ai/analyze ──► TradingAgentsGraph
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
        基本面分析师             技术面分析师           新闻/情绪分析师
                │                     │                     │
                └─────────────────────┼─────────────────────┘
                                      ▼
                              多头/空头研究员辩论
                                      │
                                      ▼
                                 交易员决策
                                      │
                                      ▼
                                 风控审核
                                      │
                                      ▼
                              SSE 流式返回结果
```

### 4.4 量化选股流

```
全A股票列表 (5513只)
        │
        ▼
  并行获取日K线 (baostock)
        │
        ▼
  ┌── 海龟交易法则 ──┐
  │  均线放量       │
  │  高窄旗形       │   ──► 综合评分 ──► 选股结果
  │  涨停洗盘       │
  │  跌停反包       │
  └── RPS 突破 ────┘
```

### 4.5 盘口异动流水线

```
AKShare 盘口异动(20类) ──► Excel 文件
                                  │
                                  ▼
                           wsqllite.py 入库
                                  │
                                  ▼
                           hzeveryday.py 汇总
                                  │
                                  ▼
                           big_buy_summary / big_deal_summary
                                  │
                                  ▼
                           K线页大单子图 + AI分析
```

## 五、API 接口总览

### 5.1 缠论接口 (chanlun-pro :9900)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tv/config` | TradingView 图表配置 |
| GET | `/tv/symbol_info` | 证券信息 |
| GET | `/tv/symbols` | 证券搜索 |
| GET | `/tv/search` | 搜索 |
| GET | `/tv/history` | K线 + 缠论绘图数据 |
| GET | `/tv/...` | 其他 TV 图表接口 |
| GET/POST | `/get_cl_config/{market}/{code}` | 缠论配置 |
| POST | `/set_cl_config` | 设置缠论配置 |
| POST | `/ticks` | Tick 数据 |
| GET | `/login` | 登录 |
| GET | `/backend/*` | 代理到 :9901 |
| GET | `/api/*` | 代理到 :9901 |
| GET | `/a-stock/*` | A-Stock SPA |

### 5.2 数据分析接口 (a-stock-backend :9901)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ping` | 心跳 |
| GET | `/api/root` | 服务状态 |
| GET | `/api/v1/kline/{symbol}` | K线 + 技术指标 |
| GET | `/api/v1/bigbuy/{symbol}` | 大单买入数据 |
| GET | `/api/v1/bigbuy-rank` | 大单买入天数排名 |
| GET | `/api/v1/stocks` | 全A股票列表 (5513只) |
| GET | `/api/v1/fundamentals/{symbol}` | 基本面 |
| GET | `/api/v1/screener` | 选股筛选 |
| GET | `/api/v1/strategy/list` | 策略列表 |
| GET | `/api/v1/strategy/picks` | 策略选股结果 |
| POST | `/api/v1/strategy/sync` | 触发选股 |
| GET | `/api/v1/strategy/signals/{symbol}` | 个股策略信号 |
| POST | `/api/ai/quick` | 快速分析 (秒级) |
| POST | `/api/ai/analyze` | 深度分析 (3-5min) |
| POST | `/api/ai/analyze/stream` | 深度分析 (SSE流式) |
| POST | `/api/auth/login` | 登录/注册 |
| GET | `/api/v1/quant/strategies` | 量化策略清单 |
| POST | `/api/v1/quant/scan` | 全市场扫描 |
| GET | `/api/v1/health` | 健康检查 |

## 六、数据库 (chanlun_klines.sqlite)

| 命名空间 | 表 | 说明 | 行数 |
|---|---|---|---|
| **原生cl_** | cl_* (11张) | chanlun-pro 自有表 | 6 |
| **K线数据** | stock_daily | 日线 (前复权) | 2,764,124 |
| | kline_cache | 多源K线缓存 | 4,271,232 |
| | trade_calendar | 交易日历 | 1,096 |
| **盘口异动** | big_buy_summary | 有大买盘汇总 | 11,906 |
| | big_deal_summary | 逐笔大单成交 | 9,878 |
| | hzeveryday | 大单柱状图数据 | 6,330 |
| | all_stcok_daydeal | 每日成交明细 | 108,301 |
| **选股** | strategy_picks | 策略选股结果 | 3,990 |
| | vol20day | 20日涨幅排名 | 3,589 |
| **股票信息** | all_stock_info | 全A股信息 | 4,939 |
| **扩展表** | user_settings, agent_session/msg/cache | 用户/Agent | 0 |
| | quant_strategy_run/hit_record | 策略运行记录 | 0 |
| | market_anomaly | 盘口异动记录 | 0 |
| | trading_calendar_ext | 交易日历扩展 | 0 |
| | user_zixuan_ext | 自选股扩展 | 0 |

**总计: 38 张表 / ~716 万行 / 1.35 GB**

## 七、部署与运维

### 7.1 服务管理

```bash
# 服务状态
systemctl --user status chanlun-pro.service    # Flask :9900
systemctl --user status a-stock-backend.service # FastAPI :9901

# 查看日志
journalctl --user -u chanlun-pro.service -f
journalctl --user -u a-stock-backend.service -f

# 重启
systemctl --user restart chanlun-pro.service
systemctl --user restart a-stock-backend.service
```

### 7.2 外网访问

```
Tailscale Funnel: https://dogzi-ms-7d73.tailbc211b.ts.net
├── /                     → 缠论 TradingView 主页
├── /a-stock/             → A-Stock 传统K线分析
└── /backend/api/*        → FastAPI 后端
```

### 7.3 数据更新

```bash
# 日线数据增量同步
cd ~/.openclaw/workspace/cl-vendors/chanlun-pro
.venv/bin/python a_stock_backend/scripts/daily_sync.py

# 盘口异动采集
.venv/bin/python a_stock_backend/scripts/pkyd.py

# 健康检查
python3 ~/.openclaw/workspace/health_check.py
```

## 八、分层融合策略

### 前端层
- chanlun-pro Jinja2 + TradingView 原界面不变
- 独立入口 `/a-stock/` 引入 Vue3 子应用
- 两套前端隔离共存

### 后端层
- Flask + Tornado WSGI 架构保持不变
- 新增 `/api/*` 和 `/backend/*` 路由代理到 FastAPI
- 复用 chanlun-pro 已有的用户认证和会话管理

### 引擎层
- Sequoia-X 量化选股 (6大策略)
- TradingAgents-CN 多Agent研判 (LangGraph编排)
- 缠论计算引擎 (PyArmor加密)
- 三个引擎各自独立，通过统一数据接口协作

### 数据层
- 统一 SQLite 数据库 (`~/.chanlun_pro/db/chanlun_klines.sqlite`)
- AKShare 作为 TDX 数据源的补充
- 盘口异动数据流水线 (20类)
