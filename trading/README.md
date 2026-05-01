# OKX 合约交易助手

深度集成 OKX 交易所 API 的 Windows 桌面端专业合约交易软件。  
解决 **交易延迟**、**仓位管理混乱**、**缺乏数据复盘** 三大痛点。

> 定位：人工辅助工具，不做自动策略执行。

---

## 项目结构

```text
okx-trading-system/
│
├── backtest/                              # 一期: 回测分析模块
│   ├── config.py                          # 全局配置
│   ├── run.py                             # 启动脚本
│   ├── analysis/
│   │   ├── basic_stats.py                 # BT-02 基础交易统计
│   │   ├── hold_loss.py                   # BT-03 扛单行为分析
│   │   ├── stoploss_sim.py                # BT-04 止损回测模拟
│   │   ├── position_tier.py               # BT-05 仓位分层分析
│   │   └── extreme_scan.py                # BT-06 极端行情扫描
│   ├── api/app.py                         # FastAPI 路由
│   ├── data/
│   │   ├── database.py                    # 数据库操作
│   │   ├── schema.py                      # SQLite 表结构
│   │   ├── loader.py                      # pkl 文件加载
│   │   ├── import_data.py                 # 数据导入管道
│   │   └── generate_sample.py             # 模拟数据生成
│   ├── models/database.py                 # 业务维度聚合查询
│   ├── static/                            # CSS/JS/Images
│   ├── templates/                         # Jinja2 模板
│   └── tests/test_all.py                  # 全流程测试
│
├── trading/                               # 二期: 交易执行模块
│   ├── config.py                          # 全局配置
│   ├── run.py                             # 启动入口
│   ├── check_env.py                       # 启动前环境校验
│   ├── requirements.txt                   # Python 依赖
│   │
│   ├── core/                              # ── 核心基础层 ──
│   │   ├── encryption.py                  # AES-256-CBC + PBKDF2
│   │   ├── credentials.py                 # API Key 加密存储
│   │   ├── session.py                     # 登录/注册/会话管理
│   │   ├── settings.py                    # 用户配置 (热更新)
│   │   └── logger.py                      # 日志 (按天滚动90天)
│   │
│   ├── data/                              # ── 数据持久化层 ──
│   │   ├── schema.py                      # SQLite 建表 (8张表)
│   │   └── database.py                    # CRUD 封装
│   │
│   ├── api/                               # ── OKX 接口层 ──
│   │   ├── okx_rest.py                    # REST 客户端 (异步 httpx)
│   │   ├── okx_ws.py                      # WebSocket (自动重连)
│   │   └── app.py                         # FastAPI (页面+API+WS推送)
│   │
│   ├── engine/                            # ── 交易引擎层 ──
│   │   ├── splitter.py                    # 智能拆单
│   │   ├── stoploss.py                    # 止损引擎
│   │   ├── order.py                       # 订单引擎
│   │   ├── position.py                    # 持仓管理
│   │   └── risk.py                        # 风控控制
│   │
│   ├── templates/index.html               # 交易界面 (暗色主题)
│   ├── static/                            # 静态资源
│   ├── db/                                # SQLite 数据库 (运行时)
│   ├── logs/                              # 运行日志 (运行时)
│   │
│   └── tests/
│       ├── test_all.py                    # 单元测试 (8项)
│       ├── test_integration.py            # 集成测试 (12项)
│       ├── mock_okx.py                    # OKX API Mock
│       └── diagnostic.py                  # 系统诊断工具
│
├── install.bat                            # Windows 安装脚本
├── start.bat                              # Windows 启动脚本
├── build.bat                              # Windows 打包脚本
├── build.spec                             # PyInstaller 配置
├── DEPLOY.md                              # 安装部署指南
├── USER_GUIDE.md                          # 用户使用手册
├── requirements.txt                       # 项目依赖
└── README.md
```

---

## 技术栈

| 组件        | 选型                                |
| ----------- | ----------------------------------- |
| 语言        | Python 3.10+                        |
| Web 框架    | FastAPI + Uvicorn                   |
| 模板引擎    | Jinja2                              |
| HTTP 客户端 | httpx (异步)                        |
| WebSocket   | websockets                          |
| 数据库      | SQLite (WAL 模式)                   |
| 加密        | AES-256-CBC + PBKDF2 (cryptography) |
| 打包        | PyInstaller                         |
| 交易所      | OKX REST API + WebSocket v5         |

---

## 功能清单

### 一期: 回测分析模块

| 编号  | 功能             | 状态 | 说明                                 |
| ----- | ---------------- | ---- | ------------------------------------ |
| BT-01 | 历史成交数据接入 | ✅   | OKX 历史成交、去重、字段统一         |
| BT-02 | 基础交易统计     | ✅   | 胜率、盈亏比、收益曲线、连赢连亏     |
| BT-03 | 扛单行为分析     | ✅   | 最大浮亏、超止损标注、分布图         |
| BT-04 | 止损回测模拟     | ✅   | 多止损比例并行对比、收益曲线         |
| BT-05 | 仓位策略分层     | ✅   | 首仓/加仓表现、对比图                |
| BT-06 | 极端行情扫描     | ✅   | 1m K线≥10%扫描、缓存去重             |
| BT-07 | 扫描断点续扫     | ✅   | 进度展示、批量限频                   |
| BT-08 | 扫描结果导出     | ✅   | 排序、筛选、CSV                      |
| BT-09 | SQLite 表设计    | ✅   | trade_records/snapshots/scan_results |
| BT-10 | 分析模块 UI      | ✅   | 看板页、扫描页、图表联动             |
| BT-11 | 结果校验测试     | ✅   | 指标复算、边界测试                   |
| BT-12 | 安装打包文档     | ✅   | Windows 打包、用户手册               |

### 二期: 交易执行模块

| 编号                 | 功能               | 状态 | 说明                                 |
| -------------------- | ------------------ | ---- | ------------------------------------ |
| **阶段一: 基础设施** |                    |      |                                      |
| TR-00                | 本地登录解锁       | ✅   | 启动密码、解锁会话、自动连接         |
| TR-00A               | 本地配置中心       | ✅   | 交易参数/快捷键/默认值热更新         |
| TR-00B               | 公告/通知/状态区   | ✅   | Toast 通知、连接状态、操作结果       |
| TR-00C               | 本地日志审计       | ✅   | 操作留痕、按天滚动、保留90天         |
| **阶段二: OKX 接口** |                    |      |                                      |
| TR-01                | OKX REST API       | ✅   | 行情/交易/账户全接口封装             |
| TR-02                | OKX WebSocket      | ✅   | ticker/orders/positions + 自动重连   |
| **阶段三: 交易引擎** |                    |      |                                      |
| TR-03                | 双通道交易框架     | ✅   | REST + WS 并发平仓、幂等容错         |
| TR-06                | 智能拆单           | ✅   | >800U 自动拆分、随机因子、总量补齐   |
| TR-08                | 强制止损引擎       | ✅   | 开仓自动挂止损、加仓后重算重挂       |
| TR-10                | 杠杆与仓位硬约束   | ✅   | 多≤3x/空≤2x、≥1500U 三档强制         |
| **阶段四: 交易界面** |                    |      |                                      |
| TR-04                | 极速下单工作台     | ✅   | 币种搜索/方向/仓位档位/杠杆/下单     |
| TR-05                | 全局快捷键         | ✅   | F1做多/F2做空/F3全平                 |
| TR-07                | 一键全平           | ✅   | 限价→超时→市价、双通道并发           |
| TR-09                | 加仓计算器         | ✅   | 读取持仓→计算25%→加仓+重挂止损       |
| TR-11                | 实时价格与连接状态 | ✅   | WS 推送、断线提示、状态栏            |
| **阶段五: 系统交付** |                    |      |                                      |
| TR-12                | API 凭证加密存储   | ✅   | AES-256 + PBKDF2、本地密码派生       |
| TR-13                | 设置中心           | ✅   | 全配置项热更新、无需重启             |
| TR-14                | 交易日志与诊断     | ✅   | 下单/撤单/平仓日志、按天滚动         |
| TR-15                | 实盘联调与测试     | ✅   | 12项集成测试、Mock API、诊断工具     |
| TR-16                | Windows 安装打包   | ✅   | install/start/build.bat、PyInstaller |

---

## API 接口

### 页面

| 路由    | 说明     |
| ------- | -------- |
| `GET /` | 交易界面 |

### 会话

| 路由                           | 方法 | 说明                          |
| ------------------------------ | ---- | ----------------------------- |
| `/api/session`                 | GET  | 会话状态 (首次/已解锁/已连接) |
| `/api/session/register`        | POST | 首次设置本地密码              |
| `/api/session/login`           | POST | 解锁会话 + 自动连接           |
| `/api/session/lock`            | POST | 锁定会话                      |
| `/api/session/change-password` | POST | 修改本地密码                  |

### 连接

| 路由              | 方法 | 说明         |
| ----------------- | ---- | ------------ |
| `/api/connect`    | POST | 手动连接 OKX |
| `/api/status`     | GET  | 连接状态     |
| `/api/diagnostic` | GET  | 系统诊断报告 |

### 交易

| 路由                   | 方法 | 说明                    |
| ---------------------- | ---- | ----------------------- |
| `/api/order`           | POST | 下单 (含拆单+自动止损)  |
| `/api/add-position`    | POST | 加仓 (25%计算+止损重挂) |
| `/api/close-all`       | POST | 一键全平                |
| `/api/positions`       | GET  | 查询持仓                |
| `/api/balance`         | GET  | 查询余额                |
| `/api/ticker/{symbol}` | GET  | 实时价格                |
| `/api/instruments`     | GET  | 合约列表                |

### 配置

| 路由                       | 方法   | 说明       |
| -------------------------- | ------ | ---------- |
| `/api/settings`            | GET    | 获取配置   |
| `/api/settings`            | POST   | 更新配置   |
| `/api/favorites`           | GET    | 常用币种   |
| `/api/logs`                | GET    | 操作日志   |
| `/api/credentials`         | GET    | 已保存凭证 |
| `/api/credentials/{label}` | DELETE | 删除凭证   |

### WebSocket

| 路由                     | 说明                                 |
| ------------------------ | ------------------------------------ |
| `ws://localhost:8888/ws` | 前端实时推送 (ticker/order/position) |

---

## 数据库表结构

| 表名                 | 用途                                     |
| -------------------- | ---------------------------------------- |
| `api_credentials`    | API Key/Secret/Passphrase (AES-256 加密) |
| `app_settings`       | 用户配置键值对                           |
| `favorite_symbols`   | 常用币种 (按使用时间排序)                |
| `trade_records`      | 本地成交记录 (开仓/平仓/盈亏)            |
| `position_snapshots` | 持仓浮盈浮亏每分钟快照                   |
| `stoploss_orders`    | 止损单记录 (触发/替换/取消)              |
| `trade_logs`         | 操作审计日志                             |
| `scan_results`       | 极端行情扫描缓存                         |

---

## 快速开始

### Windows 用户

```bash
# 1. 双击 install.bat (自动创建虚拟环境 + 安装依赖)
# 2. 双击 start.bat (环境校验 + 启动服务)
# 3. 浏览器访问 http://localhost:8888
```

### 开发者

```bash
# 安装依赖
pip install -r trading/requirements.txt

# 运行测试
cd okx-trading-system
PYTHONPATH=. python3 trading/tests/test_all.py          # 8项单元测试
PYTHONPATH=. python3 trading/tests/test_integration.py   # 12项集成测试

# 启动
PYTHONPATH=. python3 trading/run.py
```

### 打包

```bash
# 方式一: bat 脚本
双击 build.bat

# 方式二: spec 文件
pyinstaller build.spec
```

详见 [DEPLOY.md](DEPLOY.md) | [USER_GUIDE.md](USER_GUIDE.md)

---

## 性能目标

| 指标           | 目标    | 优先级 |
| -------------- | ------- | ------ |
| 下单端到端延迟 | < 50ms  | P0     |
| 价格显示刷新   | < 100ms | P0     |
| 一键全平响应   | < 200ms | P0     |
| 界面帧率       | ≥ 30fps | P1     |
| 启动时间       | < 3s    | P1     |

---

## 风控规则

| 规则           | 说明                            |
| -------------- | ------------------------------- |
| 价格止损线     | 开仓价 × 10% (固定，与杠杆无关) |
| 止损单类型     | 条件限价单 (触发后市价执行)     |
| 做多杠杆上限   | 3x                              |
| 做空杠杆上限   | 2x                              |
| 首仓           | 账户本金 50%                    |
| 第一次加仓     | 账户本金 25%                    |
| 第二次加仓     | 账户本金 25% (满仓)             |
| 仓位强制条件   | 可用余额 ≥ 1500 USDT            |
| 拆单阈值       | 单笔 > 800 USDT                 |
| 拆单随机因子   | ±5%~15% (可配置)                |
| 限价转市价超时 | 默认 3 秒 (可配置 1~30s)        |

---

## 安全机制

- API Key 使用 **AES-256-CBC** 加密，密钥从用户密码经 **PBKDF2** (600,000次迭代) 派生
- 所有请求仅发往 `api.okx.com` / `ws.okx.com`
- 无遥测、无埋点、无数据上传
- WebSocket 断线自动重连 (最大间隔 5 秒)
- 日志按天滚动，保留 90 天
- 建议：OKX API 设置 IP 白名单 + 关闭提现权限

---

## 本期排除项

- 移动端 (iOS / Android)
- macOS 支持
- 多账户 / 子账户切换
- 自动化交易策略
- 币币现货交易
- 云端数据同步

---

## 交易所API配置

- 存储位置：trading/db/trading.db → api_credentials 表（AES-256 加密）

- 配置流程：

  1.用户启动 exe → 浏览器弹出登录页 2.首次使用：设置本地密码 3.登录后弹出连接窗口，填入 API Key / Secret / Passphrase 4.点击「连接」→ 系统加密保存到 SQLite → 自动连接 OKX

下次启动： 输入本地密码 → 自动从数据库读取并解密 → 自动连接 OKX（不用再填）

- 相关代码链路：

```text
index.html (前端表单)
  → POST /api/connect
    → app.py: api_connect()
      → CredentialManager.save()  # 加密存储
      → OKXRestClient()           # 初始化连接
```

-如果你想手动查看/修改已保存的凭证：-要改 API Key 的话，锁定会话重新登录，在连接窗口重新填写即可。

```bash
# 查看 (加密后的密文，看不到明文)
sqlite3 trading/db/trading.db "SELECT label, is_demo, created_at FROM api_credentials;"

# 删除 (重新配置)
sqlite3 trading/db/trading.db "DELETE FROM api_credentials;"
```
