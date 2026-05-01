# OKX 量化回测系统

## 🛠️ 技术栈 (Tech Stack)

### 核心库

- **Python 3.10+**: 开发语言
- **FastAPI**: 高性能 Web 后端框架，支持异步及自动生成的 API 文档
- **Uvicorn**: 基于 uvloop 的 ASGI 网页服务器，用于运行 FastAPI
- **Jinja2**: HTML 模板引擎，实现前后端分离的内容渲染

### 数据处理与分析

- **Pandas**: 核心数据分析库，用于处理 K 线数据及交易记录
- **NumPy**: 科学计算库，用于高性能数值运算（如盈亏分布计算）
- **SQLite 3**: 轻量级嵌入式关系数据库，用于持久化交易流水与扫描结果
- **Pickle (pkl)**: 用于原始 K 线数据的快速序列化与反序列化

### 可视化与 UI

- **Chart.js / ECharts**: 前端数据可视化图表库（主要通过 CDN 加载）
- **Bootstrap 5**: 响应式 CSS 框架，提供统一的 UI 界面
- **HTML5 / CSS3**: 前端页面标准

---

## 🏗️ 架构概览 (Architecture)

本系统采用经典的分层架构设计，确保了数据处理、业务逻辑与 Web 展示的解耦：

- **数据层 (Data Access)**
- `data/schema.py`: 定义 SQLite 关系模型。
- `data/loader.py`: 负责高效加载大规模 Pickle 二进制行情数据。
- `data/import_data.py`: ETL 管道，处理原始数据清洗与数据库入库。

- **分析引擎层 (Analysis Engines)**:
- 独立模块化设计（BT-02 至 BT-08），每个模块专注于特定维度的量化分析（如扛单、止损模拟等）。
- 纯函数化设计，易于进行单元测试。

- **接口与展示层 (API & Presentation)**
- FastAPI 驱动的异步后端。
- 服务端渲染 (SSR) 系统，使用 Jinja2 配合 Bootstrap 实现高性能的统计看板。

---

## 项目结构

``` text
okx-trading-system/
├── backtest/
│   ├── config.py               # 全局配置
│   ├── run.py                  # 一键启动脚本
│   ├── analysis/               # 核心分析模块 (BT-02/03/04/05/06)
│   │   ├── basic_stats.py      # 基础交易统计
│   │   ├── extreme_scan.py     # 极端行情扫描
│   │   ├── hold_loss.py        # 扛单行为分析
│   │   ├── position_tier.py    # 仓位分层分析
│   │   └── stoploss_sim.py     # 止损回测模拟
│   ├── api/                    # Web API 层
│   │   └── app.py              # FastAPI 路由与中间件
│   ├── data/                   # 数据持久化与 ETL
│   │   ├── database.py         # 数据库操作工具
│   │   ├── generate_sample.py  # 模拟数据生成
│   │   ├── import_data.py      # pkl 数据导入管道
│   │   ├── loader.py           # pkl 文件底层加载
│   │   └── schema.py           # SQLite 表结构定义
│   ├── models/                 # 数据模型层
│   │   └── database.py         # 业务维度数据聚合查询
│   ├── static/                 # 静态资源 (CSS/JS/Images)
│   ├── templates/              # Jinja2 网页模板
│   └── tests/                  # 测试套件
│       └── test_all.py         # 全流程自动化测试
├── requirements.txt            # 项目依赖
└── README.md                   # 开发者文档
```

## 功能模块

### 📊 统计看板 (BT-02)

- 胜率 / 盈亏比 / 总交易笔数
- 累计收益率曲线（净值曲线）
- 最大连续盈利 / 亏损
- 盈亏分布统计
- 月度统计 / 币种统计

### ⚠️ 扛单分析 (BT-03)

- 每笔亏损交易的最大浮亏计算
- 平均最大浮亏比率
- 超止损线标注
- 散点图 / 柱状图可视化

### 🛡️ 止损回测 (BT-04)

- 多止损比例并行对比（5% / 10% / 15% / 20%）
- 模拟盈亏重算
- 多线收益曲线对比

### 📈 仓位分析 (BT-05)

- 首仓独立统计 vs 加仓后整体统计
- 加仓次数分布
- 分层对比图表

### ⚡ 极端行情扫描 (BT-06/07/08)

- 全量 K 线扫描（1min 涨跌幅 ≥ 10%）
- 排序 / 筛选 / 分页
- CSV 导出

## 测试

```bash
python backtest/tests/test_all.py
```

## API 端点

| 端点 | 方法 | 说明 |

|------|------|------|
| `/` | GET | 统计看板 |
| `/hold-loss` | GET | 扛单分析 |
| `/stoploss` | GET | 止损回测 |
| `/position` | GET | 仓位分析 |
| `/scan` | GET | 极端行情扫描 |
| `/api/summary` | GET | 交易概要 |
| `/api/basic-stats` | GET | 基础统计 |
| `/api/hold-loss` | GET | 扛单分析数据 |
| `/api/stoploss` | GET | 止损回测数据 |
| `/api/position` | GET | 仓位分析数据 |
| `/api/scan` | POST | 触发扫描 |
| `/api/scan/results` | GET | 扫描结果 |
| `/api/scan/summary` | GET | 扫描摘要 |
| `/api/scan/export` | GET | 导出 CSV |
