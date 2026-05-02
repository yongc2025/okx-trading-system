"""
数据库操作封装
"""
import sqlite3
import hashlib
import time
from typing import List, Dict, Any, Optional

import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS, TABLE_POSITION_SNAPSHOTS, TABLE_ACCOUNTS
from backtest.data.encryption import encrypt, decrypt


def save_account(
    account_name: str,
    api_key: str,
    secret: str,
    passphrase: str,
    is_demo: int = 1,
    conn: sqlite3.Connection = None
) -> str:
    """保存或更新账户信息，返回 account_id"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    
    # 生成 account_id: acc_ + name的md5前8位
    account_id = "acc_" + hashlib.md5(account_name.encode()).hexdigest()[:8]
    
    # 加密敏感信息
    enc_api = encrypt(api_key)
    enc_secret = encrypt(secret)
    enc_pass = encrypt(passphrase)
    
    conn.execute(f"""
        INSERT INTO {TABLE_ACCOUNTS} (account_id, account_name, api_key, secret, passphrase, is_demo, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(account_id) DO UPDATE SET
            account_name=excluded.account_name,
            api_key=excluded.api_key,
            secret=excluded.secret,
            passphrase=excluded.passphrase,
            is_demo=excluded.is_demo,
            updated_at=datetime('now')
    """, (account_id, account_name, enc_api, enc_secret, enc_pass, is_demo))
    
    if own_conn:
        conn.commit()
        conn.close()
    else:
        conn.commit()
    return account_id


def get_accounts(conn: sqlite3.Connection = None) -> List[Dict[str, Any]]:
    """获取所有账户（脱敏）"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.execute(f"SELECT account_id, account_name, api_key, is_demo, created_at FROM {TABLE_ACCOUNTS}")
    accounts = []
    for row in cur.fetchall():
        d = dict(row)
        # API Key 只显示前4位和后4位
        raw_api = decrypt(d['api_key'])
        d['api_key_display'] = f"{raw_api[:4]}...{raw_api[-4:]}" if len(raw_api) > 8 else "****"
        del d['api_key'] 
        accounts.append(d)
    if own_conn:
        conn.close()
    return accounts


def get_account_detail(account_id: str, conn: sqlite3.Connection = None) -> Optional[Dict[str, Any]]:
    """获取完整账户信息（解密后）"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.execute(f"SELECT * FROM {TABLE_ACCOUNTS} WHERE account_id = ?", (account_id,))
    row = cur.fetchone()
    if not row:
        if own_conn: conn.close()
        return None
    
    d = dict(row)
    d['api_key'] = decrypt(d['api_key'])
    d['secret'] = decrypt(d['secret'])
    d['passphrase'] = decrypt(d['passphrase'])
    
    if own_conn:
        conn.close()
    return d


def delete_account(account_id: str, conn: sqlite3.Connection = None):
    """删除账户及其关联数据"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    
    # 级联删除数据（如果 schema 没设级联，我们就手动删）
    conn.execute(f"DELETE FROM {TABLE_TRADE_RECORDS} WHERE account_id = ?", (account_id,))
    conn.execute(f"DELETE FROM {TABLE_ACCOUNTS} WHERE account_id = ?", (account_id,))
    
    if own_conn:
        conn.commit()
        conn.close()
    else:
        conn.commit()


def insert_trade_records(records: List[Dict], conn: sqlite3.Connection = None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cols = [
        'trade_id', 'account_id', 'symbol', 'direction', 'leverage', 'position_tier',
        'entry_time', 'entry_price', 'entry_qty', 'entry_cost',
        'exit_time', 'exit_price', 'exit_qty', 'exit_value',
        'pnl', 'pnl_rate', 'roi', 'is_win', 'is_loss',
        'max_floating_loss', 'max_floating_loss_rate', 'exceeded_stoploss',
        'account_capital',
    ]
    placeholders = ','.join(['?'] * len(cols))
    col_str = ','.join(cols)
    count = 0
    for rec in records:
        values = [rec.get(c) for c in cols]
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {TABLE_TRADE_RECORDS} ({col_str}) VALUES ({placeholders})",
                values
            )
            count += 1
        except sqlite3.IntegrityError:
            pass
    if own_conn:
        conn.commit()
        conn.close()
    else:
        conn.commit()
    return count


def insert_snapshots(snapshots: List[Dict], conn: sqlite3.Connection = None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cols = ['trade_id', 'symbol', 'snapshot_time', 'price', 'floating_pnl', 'floating_pnl_rate']
    placeholders = ','.join(['?'] * len(cols))
    col_str = ','.join(cols)
    count = 0
    for snap in snapshots:
        values = [snap.get(c) for c in cols]
        try:
            conn.execute(
                f"INSERT INTO {TABLE_POSITION_SNAPSHOTS} ({col_str}) VALUES ({placeholders})",
                values
            )
            count += 1
        except Exception:
            pass
    if own_conn:
        conn.commit()
        conn.close()
    else:
        conn.commit()
    return count


def load_trade_records_df(conn: sqlite3.Connection = None, account_id: str = None) -> pd.DataFrame:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    sql = f"SELECT * FROM {TABLE_TRADE_RECORDS}"
    params = []
    if account_id:
        sql += " WHERE account_id = ?"
        params.append(account_id)
    sql += " ORDER BY entry_time"
    df = pd.read_sql(sql, conn, params=params if params else None)
    if own_conn:
        conn.close()
    return df


def load_snapshots_for_trade(trade_id: str, conn: sqlite3.Connection = None) -> pd.DataFrame:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    df = pd.read_sql(
        f"SELECT * FROM {TABLE_POSITION_SNAPSHOTS} WHERE trade_id = ? ORDER BY snapshot_time",
        conn, params=(trade_id,)
    )
    if own_conn:
        conn.close()
    return df


def get_trade_summary(conn: sqlite3.Connection = None, account_id: str = None) -> Dict[str, Any]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    where = "WHERE account_id = ?" if account_id else ""
    params = (account_id,) if account_id else ()
    cur = conn.execute(f"""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN is_win = 1 THEN 1 END) as wins,
            COUNT(CASE WHEN is_loss = 1 THEN 1 END) as losses,
            COUNT(CASE WHEN is_win IS NULL THEN 1 END) as open_positions,
            SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
            AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
            MIN(entry_time) as first_trade,
            MAX(entry_time) as last_trade
        FROM {TABLE_TRADE_RECORDS} {where}
    """, params)
    row = cur.fetchone()
    result = dict(row) if row else {}
    if own_conn:
        conn.close()
    return result


def get_symbol_list(conn: sqlite3.Connection = None, account_id: str = None) -> List[str]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    where = "WHERE account_id = ?" if account_id else ""
    params = (account_id,) if account_id else ()
    cur = conn.execute(f"SELECT DISTINCT symbol FROM {TABLE_TRADE_RECORDS} {where} ORDER BY symbol", params)
    symbols = [row['symbol'] for row in cur.fetchall()]
    if own_conn:
        conn.close()
    return symbols


def clear_all_data(conn: sqlite3.Connection = None):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    conn.execute(f"DELETE FROM {TABLE_POSITION_SNAPSHOTS}")
    conn.execute(f"DELETE FROM {TABLE_TRADE_RECORDS}")
    conn.execute("DELETE FROM import_status")
    if own_conn:
        conn.commit()
        conn.close()
    else:
        conn.commit()