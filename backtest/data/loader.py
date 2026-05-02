"""
pkl 数据加载器
支持邢不行框架格式: Dict[str, pd.DataFrame]
"""
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.config import PKL_DATA_DIR, MIN_KLINE_COUNT, TABLE_KLINE_DATA, TABLE_DOWNLOAD_STATUS
from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS


# ===== 标准字段映射
# 兼容不同命名风格的列名
COLUMN_ALIASES = {
    "time": ["candle_begin_time", "date", "datetime", "timestamp", "time", "candle_start"],
    "open": ["open", "Open", "OPEN"],
    "high": ["high", "High", "HIGH"],
    "low": ["low", "Low", "LOW"],
    "close": ["close", "Close", "CLOSE"],
    "volume": ["volume", "Volume", "VOL", "vol", "base_vol"],
    "amount": ["amount", "Amount", "quote_vol", "turnover"],
}


def _resolve_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """从候选列名中找到实际存在的列"""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将 DataFrame 列名标准化"""
    rename_map = {}
    for std_name, aliases in COLUMN_ALIASES.items():
        if std_name in df.columns:
            continue
        found = _resolve_column(df, aliases)
        if found:
            rename_map[found] = std_name

    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def load_single_pkl(file_path: Path) -> Dict[str, pd.DataFrame]:
    """
    加载单个 pkl 文件
    返回: {symbol: DataFrame}
    """
    data = pd.read_pickle(str(file_path))

    # 情况1: Dict[str, DataFrame] - 邢不行框架标准格式
    if isinstance(data, dict):
        result = {}
        for symbol, df in data.items():
            if df is None or df.empty:
                continue
            df = _standardize_columns(df.copy())
            df.attrs['symbol'] = symbol
            result[symbol] = df
        return result

    # 情况2: 单个 DataFrame（可能有 symbol 列）
    if isinstance(data, pd.DataFrame):
        data = _standardize_columns(data)
        if 'symbol' in data.columns:
            result = {}
            for symbol, group in data.groupby('symbol'):
                group = group.copy()
                group.attrs['symbol'] = symbol
                result[str(symbol)] = group
            return result
        else:
            return {"UNKNOWN": data}

    raise ValueError(f"不支持的 pkl 数据类型: {type(data)}")


def load_all_pkl(data_dir: Path = None) -> Dict[str, pd.DataFrame]:
    """
    加载目录下所有 pkl 文件并合并
    返回: {symbol: DataFrame}
    """
    data_dir = data_dir or PKL_DATA_DIR
    if not data_dir.exists():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    pkl_files = sorted(data_dir.glob("*.pkl"))
    if not pkl_files:
        raise FileNotFoundError(f"目录下没有 pkl 文件: {data_dir}")

    all_data: Dict[str, pd.DataFrame] = {}
    for pkl_file in pkl_files:
        file_data = load_single_pkl(pkl_file)
        for symbol, df in file_data.items():
            if symbol in all_data:
                all_data[symbol] = pd.concat([all_data[symbol], df]).drop_duplicates(
                    subset=['time'] if 'time' in df.columns else None
                ).sort_values('time').reset_index(drop=True)
            else:
                all_data[symbol] = df

    return all_data


def validate_dataframe(df: pd.DataFrame, symbol: str) -> Tuple[bool, List[str]]:
    """
    验证 DataFrame 是否符合最低要求
    返回: (是否通过, 错误信息列表)
    """
    errors = []
    required = ['open', 'high', 'low', 'close']

    for col in required:
        if col not in df.columns:
            errors.append(f"[{symbol}] 缺少必要列: {col}")

    if 'time' not in df.columns:
        errors.append(f"[{symbol}] 缺少时间列 (time/candle_begin_time)")

    if len(df) < MIN_KLINE_COUNT:
        errors.append(f"[{symbol}] K线数量不足: {len(df)} < {MIN_KLINE_COUNT}")

    if df.isnull().all().any():
        null_cols = df.columns[df.isnull().all()].tolist()
        errors.append(f"[{symbol}] 以下列全为空值: {null_cols}")

    return len(errors) == 0, errors


def clean_dataframe(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    清洗单个 DataFrame
    """
    df = df.copy()

    # 确保时间列为 datetime
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.dropna(subset=['time'])
        df = df.sort_values('time').reset_index(drop=True)

    # 删除成交量为 0 的行（如有 volume 列）
    if 'volume' in df.columns:
        df = df[df['volume'] > 0].reset_index(drop=True)

    # 删除 OHLC 全为 0 的行
    ohlc_cols = [c for c in ['open', 'high', 'low', 'close'] if c in df.columns]
    if ohlc_cols:
        df = df[~(df[ohlc_cols] == 0).all(axis=1)].reset_index(drop=True)

    # 删除重复行
    df = df.drop_duplicates().reset_index(drop=True)

    # 确保数值列为 float
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df.attrs['symbol'] = symbol
    return df


def get_file_hash(file_path: Path) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def check_imported(file_path: Path, conn: sqlite3.Connection = None) -> bool:
    """检查文件是否已导入"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    cur = conn.execute(
        "SELECT status FROM import_status WHERE source_file = ?",
        (str(file_path),)
    )
    row = cur.fetchone()
    if own_conn:
        conn.close()
    return row is not None and row['status'] == 'done'


def get_kline_info() -> list[dict]:
    """
    获取 K 线数据概览（供前端 data.html 使用）

    Returns:
        [{"symbol": "BTC-USDT-SWAP", "bar": "5m", "first_time": "...", "last_time": "...", "count": 1234}, ...]
    """
    conn = get_connection()
    try:
        # 优先从 download_status 表读取（更高效）
        try:
            cur = conn.execute(
                f"SELECT symbol, bar, first_time, last_time, record_count as count "
                f"FROM {TABLE_DOWNLOAD_STATUS} ORDER BY symbol, bar"
            )
            rows = cur.fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass

        # 回退：从 kline_data 表聚合
        try:
            cur = conn.execute(
                f"SELECT symbol, bar, MIN(time) as first_time, MAX(time) as last_time, COUNT(*) as count "
                f"FROM {TABLE_KLINE_DATA} GROUP BY symbol, bar ORDER BY symbol, bar"
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []
    finally:
        conn.close()
