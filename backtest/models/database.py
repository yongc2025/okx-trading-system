"""
数据库操作封装
"""
import sqlite3
from typing import List, Dict, Any

import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS, TABLE_POSITION_SNAPSHOTS


def get_trade_summary(conn: sqlite3.Connection = None) -> Dict[str, Any]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.execute(f"""
        SELECT COUNT(*) as total,
            COUNT(CASE WHEN is_win = 1 THEN 1 END) as wins,
            COUNT(CASE WHEN is_loss = 1 THEN 1 END) as losses,
            COUNT(CASE WHEN is_win IS NULL THEN 1 END) as open_positions,
            SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
            AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
            MIN(entry_time) as first_trade,
            MAX(entry_time) as last_trade
        FROM {TABLE_TRADE_RECORDS}
    """)
    row = cur.fetchone()
    result = dict(row) if row else {}
    if own_conn:
        conn.close()
    return result


def get_symbol_list(conn: sqlite3.Connection = None) -> List[str]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.execute(f"SELECT DISTINCT symbol FROM {TABLE_TRADE_RECORDS} ORDER BY symbol")
    symbols = [row['symbol'] for row in cur.fetchall()]
    if own_conn:
        conn.close()
    return symbols