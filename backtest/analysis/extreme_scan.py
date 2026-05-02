"""
极端行情扫描引擎 (BT-06 + BT-07)
- 全量 K 线扫描（1min 涨跌幅 ≥ 10%）
- 扫描进度管理 / 断点续扫
- 结果缓存到 SQLite
"""
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

import numpy as np
import pandas as pd

from backtest.config import EXTREME_THRESHOLD, PKL_DATA_DIR
from backtest.data.loader import load_single_pkl, load_all_pkl, clean_dataframe
from backtest.data.schema import get_connection, TABLE_SCAN_RESULTS, TABLE_KLINE_DATA, TABLE_TRADE_RECORDS


def scan_single_symbol(
    symbol: str,
    df: pd.DataFrame,
    threshold: float = EXTREME_THRESHOLD,
) -> List[Dict]:
    """
    扫描单个币种的极端行情

    Args:
        symbol: 币种名
        df: K 线 DataFrame
        threshold: 涨跌幅阈值 (如 0.10 表示 10%)

    Returns:
        极端行情列表
    """
    results = []

    if df.empty or 'close' not in df.columns:
        return results

    # 确保时间列
    time_col = None
    for col in ['time', 'candle_begin_time', 'date', 'datetime']:
        if col in df.columns:
            time_col = col
            break

    if time_col is None:
        return results

    # 计算涨跌幅
    df = df.copy()
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')

    if 'volume' in df.columns:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    else:
        df['volume'] = 0

    # 涨跌幅 = (close - open) / open
    df['change_pct'] = (df['close'] - df['open']) / df['open'].replace(0, np.nan)

    # 筛选超过阈值的
    extreme = df[df['change_pct'].abs() >= threshold].copy()

    for _, row in extreme.iterrows():
        change = float(row['change_pct'])
        results.append({
            'symbol': symbol,
            'scan_time': str(row[time_col]),
            'direction': 'surge' if change > 0 else 'plunge',
            'change_pct': round(change, 6),
            'open_price': round(float(row['open']), 6),
            'close_price': round(float(row['close']), 6),
            'high_price': round(float(row['high']), 6) if pd.notna(row.get('high')) else None,
            'low_price': round(float(row['low']), 6) if pd.notna(row.get('low')) else None,
            'volume': round(float(row['volume']), 2) if pd.notna(row.get('volume')) else 0,
            'data_source': 'pkl',
        })

    return results


def _get_order_symbols(conn: sqlite3.Connection) -> set:
    """从交易记录表获取所有涉及的币种"""
    try:
        cur = conn.execute(f"SELECT DISTINCT symbol FROM {TABLE_TRADE_RECORDS}")
        return {row['symbol'] for row in cur.fetchall()}
    except Exception:
        return set()


def _load_kline_data(
    conn: sqlite3.Connection,
    symbols: set = None,
    data_dir: Path = None,
) -> Dict[str, pd.DataFrame]:
    """
    加载 K 线数据，优先从数据库读取，其次从 pkl 文件

    Args:
        conn: 数据库连接（必须传入）
        symbols: 只加载这些币种的数据，None 表示全部
        data_dir: pkl 备选目录

    Returns:
        {symbol: DataFrame}
    """
    # 1. 优先从数据库读取
    try:
        cur = conn.execute(f"SELECT COUNT(*) as cnt FROM {TABLE_KLINE_DATA}")
        row = cur.fetchone()
        db_count = row['cnt'] if row else 0
    except Exception:
        db_count = 0

    if db_count > 0:
        if symbols:
            placeholders = ','.join(['?'] * len(symbols))
            df = pd.read_sql(
                f"SELECT symbol, time, open, high, low, close, volume "
                f"FROM {TABLE_KLINE_DATA} WHERE symbol IN ({placeholders}) "
                f"ORDER BY symbol, time",
                conn, params=list(symbols),
            )
        else:
            df = pd.read_sql(
                f"SELECT symbol, time, open, high, low, close, volume "
                f"FROM {TABLE_KLINE_DATA} ORDER BY symbol, time",
                conn,
            )
        result = {}
        for sym, group in df.groupby('symbol'):
            result[str(sym)] = group.reset_index(drop=True)
        if result:
            return result

    # 2. 回退到 pkl 文件
    data_dir = data_dir or PKL_DATA_DIR
    all_data = load_all_pkl(data_dir)
    if symbols:
        all_data = {k: v for k, v in all_data.items() if k in symbols}
    return all_data


def scan_all_symbols(
    data_dir: Path = None,
    threshold: float = EXTREME_THRESHOLD,
    conn: sqlite3.Connection = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    扫描所有币种的极端行情

    Args:
        data_dir: pkl 数据目录
        threshold: 涨跌幅阈值
        conn: 数据库连接
        progress_callback: 进度回调 callback(current, total, symbol)

    Returns:
        扫描结果摘要
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    data_dir = data_dir or PKL_DATA_DIR

    # 获取订单涉及的币种
    order_symbols = _get_order_symbols(conn)

    # 加载数据（只加载订单涉及的币种）
    try:
        all_data = _load_kline_data(conn, symbols=order_symbols or None, data_dir=data_dir)
    except FileNotFoundError as e:
        if own_conn:
            conn.close()
        return {"error": f"无 K 线数据: {e}。请先在数据管理页面下载 K 线"}
    except Exception as e:
        if own_conn:
            conn.close()
        return {"error": f"加载 K 线数据失败: {e}"}

    total_symbols = len(all_data)
    total_extreme = 0
    scanned = 0
    errors = []

    for i, (symbol, raw_df) in enumerate(all_data.items()):
        if progress_callback:
            progress_callback(i + 1, total_symbols, symbol)

        try:
            # 清洗
            df = clean_dataframe(raw_df, symbol)
            if df.empty:
                continue

            # 扫描
            results = scan_single_symbol(symbol, df, threshold)

            # 写入数据库
            for rec in results:
                try:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {TABLE_SCAN_RESULTS} "
                        f"(symbol, scan_time, direction, change_pct, open_price, close_price, "
                        f"high_price, low_price, volume, data_source) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            rec['symbol'], rec['scan_time'], rec['direction'],
                            rec['change_pct'], rec['open_price'], rec['close_price'],
                            rec['high_price'], rec['low_price'], rec['volume'],
                            rec['data_source'],
                        )
                    )
                except Exception:
                    pass

            total_extreme += len(results)
            scanned += 1

        except Exception as e:
            errors.append(f"{symbol}: {str(e)}")

    if own_conn:
        conn.commit()
        conn.close()

    return {
        "total_symbols": total_symbols,
        "scanned_symbols": scanned,
        "total_extreme_events": total_extreme,
        "threshold": threshold,
        "threshold_pct": f"{threshold * 100:.0f}%",
        "errors": errors[:10],  # 最多返回 10 个错误
    }


_SCAN_VALID_ORDER_FIELDS = frozenset({
    'change_pct', 'scan_time', 'volume', 'symbol', 'open_price', 'close_price',
})


def get_scan_results(
    conn: sqlite3.Connection = None,
    symbol: str = None,
    direction: str = None,
    min_pct: float = None,
    limit: int = 100,
    order_by: str = 'change_pct',
    order_desc: bool = True,
) -> pd.DataFrame:
    """
    查询扫描结果

    Args:
        conn: 数据库连接
        symbol: 币种筛选
        direction: 方向筛选 (surge/plunge)
        min_pct: 最小涨跌幅绝对值
        limit: 返回条数
        order_by: 排序字段（白名单校验）
        order_desc: 是否降序
    """
    # 白名单校验，防止 SQL 注入
    if order_by not in _SCAN_VALID_ORDER_FIELDS:
        order_by = 'change_pct'

    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    query = f"SELECT * FROM {TABLE_SCAN_RESULTS} WHERE 1=1"
    params = []

    if symbol:
        query += " AND symbol = ?"
        params.append(symbol)

    if direction:
        query += " AND direction = ?"
        params.append(direction)

    if min_pct is not None:
        query += " AND ABS(change_pct) >= ?"
        params.append(min_pct)

    order_dir = "DESC" if order_desc else "ASC"
    query += f" ORDER BY {order_by} {order_dir} LIMIT ?"
    params.append(limit)

    df = pd.read_sql(query, conn, params=params)

    if own_conn:
        conn.close()

    return df


def get_scan_summary(conn: sqlite3.Connection = None) -> Dict[str, Any]:
    """获取扫描结果摘要"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    cur = conn.execute(f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT symbol) as symbols,
            COUNT(CASE WHEN direction = 'surge' THEN 1 END) as surges,
            COUNT(CASE WHEN direction = 'plunge' THEN 1 END) as plunges,
            AVG(ABS(change_pct)) as avg_change_pct,
            MAX(ABS(change_pct)) as max_change_pct,
            MIN(change_pct) as min_change,
            MAX(change_pct) as max_change
        FROM {TABLE_SCAN_RESULTS}
    """)
    row = cur.fetchone()
    result = dict(row) if row else {}

    # 按币种统计
    cur2 = conn.execute(f"""
        SELECT symbol, COUNT(*) as events,
               AVG(ABS(change_pct)) as avg_pct,
               MAX(ABS(change_pct)) as max_pct
        FROM {TABLE_SCAN_RESULTS}
        GROUP BY symbol
        ORDER BY events DESC
        LIMIT 20
    """)
    result['top_symbols'] = [dict(r) for r in cur2.fetchall()]

    if own_conn:
        conn.close()

    return result


def export_scan_results_csv(
    output_path: Path,
    conn: sqlite3.Connection = None,
    **filters,
) -> int:
    """
    导出扫描结果为 CSV

    Returns:
        导出行数
    """
    df = get_scan_results(conn=conn, limit=999999, **filters)
    df.to_csv(str(output_path), index=False, encoding='utf-8-sig')
    return len(df)
