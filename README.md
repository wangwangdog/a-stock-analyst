# 📊 A-Stock Analyst

A 股数据分析 Web 工具，手机端适配。胖磊 🦞 出品。

## 功能

- ✅ **K 线图表** — 日K/周K/月K，带 MA/MACD/RSI/布林带/KDJ
- ✅ **基本面数据** — 市值、行业、股本
- ✅ **双源校验** — AKShare + Baostock 数据交叉验证
- ✅ **选股筛选** — 按行业、市值过滤
- ✅ **移动端适配** — 手机友好

## 快速启动

```bash
cd a-stock-analyst
bash start.sh
```

然后访问 http://localhost:3000

## 手动启动

### 后端
```bash
cd backend
PYTHONPATH="." python3 -m uvicorn main:app --host 0.0.0.0 --port 8765
```

### 前端
```bash
cd frontend
npx vite --host 0.0.0.0 --port 3000
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python FastAPI + AKShare + Baostock |
| 前端 | Vue3 + Vant 4 + lightweight-charts |
| 数据 | SQLite 本地缓存 |
| 校验 | 双源交叉验证 + 日志追溯 |

## 目录结构

```
a-stock-analyst/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置
│   ├── data/
│   │   ├── akshare_fetcher.py   # AKShare 数据源
│   │   ├── baostock_fetcher.py  # Baostock 数据源
│   │   ├── validator.py     # 交叉校验器
│   │   └── cache.py         # SQLite 缓存
│   ├── analysis/
│   │   ├── indicators.py    # 技术指标
│   │   └── fundamentals.py  # 基本面分析
│   └── routes/
│       └── kline.py         # API 路由
├── frontend/
│   ├── src/
│   │   ├── views/           # 页面
│   │   ├── router/          # 路由
│   │   └── utils/           # API 客户端
│   └── package.json
└── start.sh
```
