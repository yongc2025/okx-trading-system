"""
SQLite 数据库表结构定义与初始化
"""
import sqlite3
from backtest.config import (
    DB_PATH, DATA_DIR,
    TABLE_TRADE_RECORDS, TABLE_POSITION_SNAPSHOTS,
    TABLE_SCAN_RESULTS, TABLE_APP_SETTINGS,
    TABLE_KLINE_DATA, TABLE_DOWNLOAD_STATUS,
)


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """获取数据库连接"""
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str = None) -> sqlite3.Connection:
    """初始化数据库，创建所有表"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # ---- 1. 交易记录表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_TRADE_RECORDS} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id        TEXT UNIQUE,
        symbol          TEXT NOT NULL,
        direction       TEXT NOT NULL,
        leverage        INTEGER DEFAULT 1,
        position_tier   TEXT,
        entry_time      TEXT NOT NULL,
        entry_price     REAL NOT NULL,
        entry_qty       REAL NOT NULL,
        entry_cost      REAL NOT NULL,
        exit_time       TEXT,
        exit_price      REAL,
        exit_qty        REAL,
        exit_value      REAL,
        pnl             REAL,
        pnl_rate        REAL,
        roi             REAL,
        is_win          INTEGER,
        is_loss         INTEGER,
        max_floating_loss       REAL DEFAULT 0,
        max_floating_loss_rate  REAL DEFAULT 0,
        exceeded_stoploss       INTEGER DEFAULT 0,
        account_capital REAL,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """)
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trade_symbol ON {TABLE_TRADE_RECORDS}(symbol)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trade_time ON {TABLE_TRADE_RECORDS}(entry_time)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trade_direction ON {TABLE_TRADE_RECORDS}(direction)")

    # ---- 2. 持仓快照表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_POSITION_SNAPSHOTS} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id        TEXT NOT NULL,
        symbol          TEXT NOT NULL,
        snapshot_time   TEXT NOT NULL,
        price           REAL NOT NULL,
        floating_pnl    REAL NOT NULL,
        floating_pnl_rate REAL NOT NULL,
        FOREIGN KEY (trade_id) REFERENCES {TABLE_TRADE_RECORDS}(trade_id)
    )
    """)
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_snap_trade ON {TABLE_POSITION_SNAPSHOTS}(trade_id)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_snap_time ON {TABLE_POSITION_SNAPSHOTS}(snapshot_time)")

    # ---- 3. 极端行情扫描结果表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_SCAN_RESULTS} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT NOT NULL,
        scan_time       TEXT NOT NULL,
        direction       TEXT NOT NULL,
        change_pct      REAL NOT NULL,
        open_price      REAL NOT NULL,
        close_price     REAL NOT NULL,
        high_price      REAL,
        low_price       REAL,
        volume          REAL,
        data_source     TEXT DEFAULT 'pkl',
        UNIQUE(symbol, scan_time)
    )
    """)
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_symbol ON {TABLE_SCAN_RESULTS}(symbol)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_time ON {TABLE_SCAN_RESULTS}(scan_time)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scan_pct ON {TABLE_SCAN_RESULTS}(change_pct)")

    # ---- 4. 应用设置表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_APP_SETTINGS} (
        key             TEXT PRIMARY KEY,
        value           TEXT NOT NULL,
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """)

    # ---- 5. K 线数据表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_KLINE_DATA} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT NOT NULL,
        bar             TEXT NOT NULL,
        time            TEXT NOT NULL,
        open            REAL NOT NULL,
        high            REAL NOT NULL,
        low             REAL NOT NULL,
        close           REAL NOT NULL,
        volume          REAL,
        amount          REAL,
        source          TEXT DEFAULT 'okx',
        UNIQUE(symbol, bar, time)
    )
    """)
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_kline_sym_bar ON {TABLE_KLINE_DATA}(symbol, bar)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_kline_time ON {TABLE_KLINE_DATA}(time)")

    # ---- 6. 下载状态表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_DOWNLOAD_STATUS} (
        symbol          TEXT NOT NULL,
        bar             TEXT NOT NULL,
        first_time      TEXT,
        last_time       TEXT,
        record_count    INTEGER DEFAULT 0,
        updated_at      TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (symbol, bar)
    )
    """)

    # ---- 5. 数据导入状态表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS import_status (
        source_file     TEXT PRIMARY KEY,
        file_hash       TEXT,
        symbol_count    INTEGER,
        record_count    INTEGER,
        imported_at     TEXT DEFAULT (datetime('now')),
        status          TEXT DEFAULT 'done'
    )
    """)

    conn.commit()
    return conn


def reset_database(db_path: str = None):
    """重置数据库（删除所有表并重建）"""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cursor.fetchall()]
    for table in tables:
        if not table.startswith('sqlite_'):
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()
    return init_database(db_path)
