"""
OKX 交易助手 - 全局配置
交易执行模块配置项
"""
import os
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "db"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "trading.db"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ============================================================
# OKX API 配置
# ============================================================
OKX_REST_BASE = "https://www.okx.com"
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
OKX_WS_PRIVATE = "wss://ws.okx.com:8443/ws/v5/private"
OKX_WS_BUSINESS = "wss://ws.okx.com:8443/ws/v5/business"

# 模拟盘 REST 地址 (OKX 模拟盘也映射在主站，主要靠 Header 区分)
OKX_REST_DEMO = "https://www.okx.com"
OKX_WS_PUBLIC_DEMO = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
OKX_WS_PRIVATE_DEMO = "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999"

# ============================================================
# 网络代理配置
# ============================================================
# 如果在国内运行，请配置您的 VPN 代理端口
# 注意：如果使用 socks5h:// 报错，请改回 http://
# v2rayN 默认 HTTP 端口通常是 10809
PROXY_URL = "http://127.0.0.1:10808" 

# ============================================================
# 交易参数默认值
# ============================================================
DEFAULT_LEVERAGE_LONG = 3       # 做多默认杠杆
DEFAULT_LEVERAGE_LONG_MAX = 3   # 做多杠杆上限
DEFAULT_LEVERAGE_SHORT = 2      # 做空默认杠杆
DEFAULT_LEVERAGE_SHORT_MAX = 2  # 做空杠杆上限

SPLIT_THRESHOLD_USDT = 800      # 拆单阈值 (USDT)
SPLIT_RANDOM_RANGE = (0.05, 0.15)  # 拆单随机浮动范围

POSITION_TIER_1 = 0.50  # 首仓 50%
POSITION_TIER_2 = 0.25  # 第一次加仓 25%
POSITION_TIER_3 = 0.25  # 第二次加仓 25%
POSITION_MIN_BALANCE = 1500  # 仓位分配强制执行最低余额 (USDT)

STOPLOSS_PRICE_RATIO = 0.10  # 价格止损线 = 开仓价 × 10%
LIMIT_TO_MARKET_TIMEOUT = 3  # 限价转市价超时 (秒)

# ============================================================
# WebSocket 配置
# ============================================================
WS_RECONNECT_INTERVAL = 2     # 重连间隔 (秒)
WS_RECONNECT_MAX = 5          # 最大重连间隔 (秒)
WS_PING_INTERVAL = 15         # 心跳间隔 (秒)

# ============================================================
# 日志配置
# ============================================================
LOG_MAX_DAYS = 90  # 日志保留天数

# ============================================================
# 加密配置
# ============================================================
ENCRYPTION_ITERATIONS = 600_000  # PBKDF2 迭代次数
ENCRYPTION_KEY_LENGTH = 32       # 密钥长度 (256 bit)
ENCRYPTION_SALT_LENGTH = 16      # 盐长度

# ============================================================
# 性能目标
# ============================================================
TARGET_ORDER_LATENCY_MS = 50      # 下单端到端延迟目标 (ms)
TARGET_PRICE_LATENCY_MS = 100     # 价格刷新延迟目标 (ms)
TARGET_CLOSEALL_LATENCY_MS = 200  # 一键全平响应目标 (ms)
