"""
OKX 交易助手 - SQLite 表结构定义
交易执行模块数据库 Schema
"""
import sqlite3
from pathlib import Path


SCHEMA_SQL = """
-- ============================================================
-- API 凭证 (AES-256 加密存储)
-- ============================================================
CREATE TABLE IF NOT EXISTS api_credentials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL DEFAULT 'default',
    api_key     TEXT NOT NULL,        -- AES-256 加密后的密文
    secret      TEXT NOT NULL,        -- AES-256 加密后的密文
    passphrase  TEXT NOT NULL,        -- AES-256 加密后的密文
    is_demo     INTEGER NOT NULL DEFAULT 0,  -- 1=模拟盘 0=实盘
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(label)
);

-- ============================================================
-- 用户配置 (键值对)
-- ============================================================
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- 常用币种
-- ============================================================
CREATE TABLE IF NOT EXISTS favorite_symbols (
    symbol      TEXT PRIMARY KEY,     -- 如 BTC-USDT-SWAP
    last_used   TEXT NOT NULL DEFAULT (datetime('now')),
    use_count   INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- 本地成交记录
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT,                 -- OKX 订单 ID
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,        -- buy / sell
    direction       TEXT NOT NULL,        -- long / short
    price           REAL NOT NULL,
    quantity        REAL NOT NULL,
    notional        REAL NOT NULL,        -- 名义价值 (USDT)
    leverage        INTEGER NOT NULL,
    position_tier   TEXT NOT NULL,        -- first / add1 / add2
    open_price      REAL,                 -- 开仓均价 (加仓后更新)
    stoploss_price  REAL,                 -- 止损价
    pnl             REAL,                 -- 平仓盈亏
    fee             REAL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'open',  -- open / closed / cancelled
    okx_ts          TEXT,                 -- OKX 返回的时间戳
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);

-- ============================================================
-- 持仓快照 (每分钟浮盈浮亏)
-- ============================================================
CREATE TABLE IF NOT EXISTS position_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry_price REAL NOT NULL,
    mark_price  REAL NOT NULL,
    quantity    REAL NOT NULL,
    unrealized_pnl   REAL NOT NULL,
    unrealized_ratio REAL NOT NULL,
    ts          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- 止损单记录
-- ============================================================
CREATE TABLE IF NOT EXISTS stoploss_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL,
    trigger_price   REAL NOT NULL,
    order_price     REAL,                 -- 触发后挂单价 (市价则为 NULL)
    order_type      TEXT NOT NULL DEFAULT 'conditional_market',  -- conditional_market / conditional_limit
    okx_order_id    TEXT,                 -- OKX 条件单 ID
    status          TEXT NOT NULL DEFAULT 'active',  -- active / triggered / cancelled / replaced
    parent_sl_id    INTEGER,              -- 被替换的旧止损单 ID
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- 交易日志 (操作审计)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL DEFAULT 'INFO',  -- INFO / WARN / ERROR
    action      TEXT NOT NULL,          -- order / cancel / close / stoploss / login / config_change
    symbol      TEXT,
    detail      TEXT,                   -- JSON 格式详细信息
    latency_ms  REAL,                  -- 操作耗时 (ms)
    result      TEXT,                   -- success / fail
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- 极端行情扫描结果缓存 (与 backtest 模块共享)
-- ============================================================
CREATE TABLE IF NOT EXISTS scan_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    direction   TEXT NOT NULL,           -- surge / plunge
    change_pct  REAL NOT NULL,
    open_price  REAL NOT NULL,
    close_price REAL NOT NULL,
    UNIQUE(symbol, ts)
);

-- ============================================================
-- 索引
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_trade_records_symbol ON trade_records(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_records_status ON trade_records(status);
CREATE INDEX IF NOT EXISTS idx_trade_records_created ON trade_records(created_at);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_ts ON position_snapshots(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_stoploss_orders_status ON stoploss_orders(status);
CREATE INDEX IF NOT EXISTS idx_trade_logs_created ON trade_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_trade_logs_action ON trade_logs(action);
"""


def init_db(db_path: Path = None) -> sqlite3.Connection:
    """初始化数据库，返回连接"""
    if db_path is None:
        from trading.config import DB_PATH
        db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
