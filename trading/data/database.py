"""
OKX 交易助手 - 数据库操作工具
"""
import sqlite3
import json
from datetime import datetime
from typing import Any, Optional
from contextlib import contextmanager

from trading.data.schema import init_db


class Database:
    """SQLite 数据库封装"""

    def __init__(self, db_path=None):
        self._conn = init_db(db_path)

    @contextmanager
    def transaction(self):
        """事务上下文管理器"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [d[0] for d in cur.description]
        return dict(zip(columns, row))

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self._conn.execute(sql, params)
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    # ----------------------------------------------------------
    # 设置
    # ----------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.fetchone(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        )
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set_setting(self, key: str, value: Any):
        with self.transaction():
            self.execute(
                "INSERT OR REPLACE INTO app_settings(key, value, updated_at) VALUES(?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), datetime.utcnow().isoformat()),
            )

    # ----------------------------------------------------------
    # 常用币种
    # ----------------------------------------------------------
    def touch_favorite(self, symbol: str):
        with self.transaction():
            self.execute(
                """INSERT INTO favorite_symbols(symbol, last_used, use_count) VALUES(?,?,1)
                   ON CONFLICT(symbol) DO UPDATE SET
                     last_used=datetime('now'), use_count=use_count+1""",
                (symbol, datetime.utcnow().isoformat()),
            )

    def get_favorites(self, limit: int = 20) -> list[dict]:
        return self.fetchall(
            "SELECT symbol, last_used, use_count FROM favorite_symbols ORDER BY last_used DESC LIMIT ?",
            (limit,),
        )

    # ----------------------------------------------------------
    # 成交记录
    # ----------------------------------------------------------
    def insert_trade(self, **kwargs) -> int:
        # S-01 修复: 添加列名白名单校验，防止 SQL 注入
        allowed_columns = {
            "order_id", "symbol", "side", "direction", "price", "quantity", 
            "notional", "leverage", "position_tier", "open_price", 
            "stoploss_price", "pnl", "fee", "status", "okx_ts", "closed_at"
        }
        invalid = set(kwargs.keys()) - allowed_columns
        if invalid:
            raise ValueError(f"非法列名: {invalid}")

        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        with self.transaction():
            cur = self.execute(
                f"INSERT INTO trade_records({columns}) VALUES({placeholders})",
                tuple(kwargs.values()),
            )
            return cur.lastrowid

    def update_trade(self, trade_id: int, **kwargs):
        # S-01 修复: 添加列名白名单校验，防止 SQL 注入
        allowed_columns = {
            "order_id", "price", "quantity", "notional", "leverage", 
            "position_tier", "open_price", "stoploss_price", "pnl", 
            "fee", "status", "okx_ts", "closed_at"
        }
        invalid = set(kwargs.keys()) - allowed_columns
        if invalid:
            raise ValueError(f"非法列名: {invalid}")

        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self.transaction():
            self.execute(
                f"UPDATE trade_records SET {sets} WHERE id=?",
                (*kwargs.values(), trade_id),
            )

    def get_open_trades(self, symbol: str = None) -> list[dict]:
        if symbol:
            return self.fetchall(
                "SELECT * FROM trade_records WHERE status='open' AND symbol=?", (symbol,)
            )
        return self.fetchall("SELECT * FROM trade_records WHERE status='open'")

    # ----------------------------------------------------------
    # 止损单
    # ----------------------------------------------------------
    def insert_stoploss(self, **kwargs) -> int:
        allowed_columns = {
            "symbol", "direction", "trigger_price", "order_price",
            "order_type", "okx_order_id", "status", "parent_sl_id"
        }
        invalid = set(kwargs.keys()) - allowed_columns
        if invalid:
            raise ValueError(f"非法列名: {invalid}")
        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        with self.transaction():
            cur = self.execute(
                f"INSERT INTO stoploss_orders({columns}) VALUES({placeholders})",
                tuple(kwargs.values()),
            )
            return cur.lastrowid

    def update_stoploss(self, sl_id: int, **kwargs):
        allowed_columns = {
            "trigger_price", "order_price", "order_type",
            "okx_order_id", "status", "parent_sl_id"
        }
        invalid = set(kwargs.keys()) - allowed_columns
        if invalid:
            raise ValueError(f"非法列名: {invalid}")
        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self.transaction():
            self.execute(
                f"UPDATE stoploss_orders SET {sets} WHERE id=?",
                (*kwargs.values(), sl_id),
            )

    def get_active_stoploss(self, symbol: str) -> Optional[dict]:
        return self.fetchone(
            "SELECT * FROM stoploss_orders WHERE symbol=? AND status='active' ORDER BY id DESC LIMIT 1",
            (symbol,),
        )

    # ----------------------------------------------------------
    # 交易日志
    # ----------------------------------------------------------
    def log(self, action: str, detail: Any = None, symbol: str = None,
            level: str = "INFO", latency_ms: float = None, result: str = None):
        detail_str = json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else detail
        with self.transaction():
            self.execute(
                "INSERT INTO trade_logs(level, action, symbol, detail, latency_ms, result) VALUES(?,?,?,?,?,?)",
                (level, action, symbol, detail_str, latency_ms, result),
            )

    # ----------------------------------------------------------
    # 持仓快照
    # ----------------------------------------------------------
    def insert_snapshot(self, **kwargs):
        allowed_columns = {
            "symbol", "direction", "entry_price", "mark_price",
            "quantity", "unrealized_pnl", "unrealized_ratio"
        }
        invalid = set(kwargs.keys()) - allowed_columns
        if invalid:
            raise ValueError(f"非法列名: {invalid}")
        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        with self.transaction():
            self.execute(
                f"INSERT INTO position_snapshots({columns}) VALUES({placeholders})",
                tuple(kwargs.values()),
            )

    def close(self):
        self._conn.close()
