"""
OKX 量化回测系统 - 全局配置
"""
from pathlib import Path

# ===== 路径配置
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "backtest.db"
PKL_DATA_DIR = DATA_DIR / "pkl"  # pkl 文件存放目录
LOG_DIR = PROJECT_ROOT / "logs"  # 日志目录

# 确保文件夹存在
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===== 数据库表名
TABLE_TRADE_RECORDS = "trade_records"
TABLE_POSITION_SNAPSHOTS = "position_snapshots"
TABLE_SCAN_RESULTS = "scan_results"
TABLE_APP_SETTINGS = "app_settings"
TABLE_KLINE_DATA = "kline_data"
TABLE_DOWNLOAD_STATUS = "download_status"
TABLE_ACCOUNTS = "accounts"

# ===== 加密配置
ENCRYPTION_KEY_FILE = DATA_DIR / ".key"
ENCRYPTION_SALT_LENGTH = 16
ENCRYPTION_ITERATIONS = 100_000
ENCRYPTION_KEY_LENGTH = 32  # AES-256

# ===== 下载参数
DOWNLOAD_BATCH_SIZE = 100  # 每次拉取 K 线条数

# ===== 止损回测默认参数
DEFAULT_STOPLOSS_RATIOS = [0.05, 0.10, 0.15, 0.20]

# ===== 极端行情扫描参数
EXTREME_THRESHOLD = 0.10  # 1min K 线涨跌幅阈值 10%
EXTREME_KLINE_PERIOD = "1min"

# ===== 仓位分配规则
POSITION_TIERS = {
    "first": 0.50,    # 首仓 50%
    "add1": 0.25,     # 第一次加仓 25%
    "add2": 0.25,     # 第二次加仓 25%
}
MIN_CAPITAL_FOR_TIER = 1500  # USDT，低于此值仓位规则放开

# ===== 杠杆上限
LEVERAGE_LIMITS = {
    "long": 3,   # 做多最高 3x
    "short": 2,  # 做空最高 2x
}

# ===== 数据清洗参数
MIN_KLINE_COUNT = 100  # 最少 K 线数量，不足则剔除

# ===== Web 服务配置
WEB_HOST = "0.0.0.0"
WEB_PORT = 8080