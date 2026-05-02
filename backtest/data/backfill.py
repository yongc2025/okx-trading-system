"""
补算 max_floating_loss 字段
当用户通过CSV导入订单后，系统根据K线数据自动计算每笔交易的最大浮亏
"""
import sqlite3
from datetime import datetime
from typing import Dict, Any

import numpy as np
import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS, TABLE_KLINE_DATA
from backtest.data.loader import load_all_pkl, clean_dataframe
from backtest.config import PKL_DATA_DIR


def _calc_max_floating_loss_from_klines(
    entry_price: float,
    exit_price: float,
    direction: str,
    entry_cost: float,
    leverage: int,
    kline_period: pd.DataFrame,
) -> Dict[str, float]:
    """
    根据K线数据计算最大浮亏

    Args:
        entry_price: 开仓价
        exit_price: 平仓价
        direction: long/short
        entry_cost: 开仓成本
        leverage: 杠杆
        kline_period: 持仓期间的K线 DataFrame (含 high, low 列)

    Returns:
        {"max_floating_loss": float, "max_floating_loss_rate": float}
    """
    if kline_period.empty:
        return {"max_floating_loss": 0.0, "max_floating_loss_rate": 0.0}

    capital = entry_cost  # 用 entry_cost 作为基准

    if direction == "long":
        # 做多：最低价时浮亏最大
        min_price = float(kline_period["low"].min())
        max_floating_loss = (min_price - entry_price) / entry_price * entry_cost * leverage
    else:
        # 做空：最高价时浮亏最大
        max_price = float(kline_period["high"].max())
        max_floating_loss = (entry_price - max_price) / entry_price * entry_cost * leverage

    max_floating_loss = min(max_floating_loss, 0.0)  # 只取亏损方向
    max_floating_loss_rate = abs(max_floating_loss) / capital if max_floating_loss < 0 else 0.0

    return {
        "max_floating_loss": round(max_floating_loss, 2),
        "max_floating_loss_rate": round(max_floating_loss_rate, 6),
    }


def backfill_from_db_klines(conn: sqlite3.Connection = None) -> Dict[str, Any]:
    """
    从数据库 kline_data 表补算所有 max_floating_loss=0 的交易记录

    Returns:
        {"updated": 50, "skipped": 30, "errors": [...]}
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    updated = 0
    skipped = 0
    errors = []

    try:
        # 读取需要补算的交易（max_floating_loss_rate 为 0 或 NULL）
        trades = pd.read_sql(
            f"SELECT * FROM {TABLE_TRADE_RECORDS} "
            f"WHERE (max_floating_loss_rate IS NULL OR max_floating_loss_rate = 0) "
            f"AND pnl IS NOT NULL "
            f"ORDER BY entry_time",
            conn,
        )

        if trades.empty:
            return {"updated": 0, "skipped": 0, "errors": [], "message": "没有需要补算的交易"}

        # 读取所有K线数据
        klines = pd.read_sql(
            f"SELECT symbol, time, high, low FROM {TABLE_KLINE_DATA} ORDER BY symbol, time",
            conn,
        )

        if klines.empty:
            return {
                "updated": 0, "skipped": len(trades),
                "errors": [], "message": "数据库中没有K线数据，请先下载K线"
            }

        klines["time"] = pd.to_datetime(klines["time"])

        # 按币种分组
        kline_groups = {sym: group for sym, group in klines.groupby("symbol")}

        cursor = conn.cursor()

        for _, trade in trades.iterrows():
            symbol = trade["symbol"]
            entry_time = pd.to_datetime(trade["entry_time"])
            exit_time = pd.to_datetime(trade["exit_time"])
            entry_price = float(trade["entry_price"])
            exit_price = float(trade["exit_price"])
            direction = trade["direction"]
            entry_cost = float(trade["entry_cost"])
            leverage = int(trade["leverage"])

            # 尝试精确匹配币种
            kline_df = kline_groups.get(symbol)

            # 模糊匹配（去掉 -SWAP 后缀等）
            if kline_df is None:
                for k, v in kline_groups.items():
                    if symbol.startswith(k) or k.startswith(symbol.split("-")[0]):
                        kline_df = v
                        break

            if kline_df is None:
                skipped += 1
                continue

            # 筛选持仓期间的K线
            period = kline_df[
                (kline_df["time"] >= entry_time) & (kline_df["time"] <= exit_time)
            ]

            if period.empty:
                # 尝试扩大范围
                period = kline_df[
                    (kline_df["time"] >= entry_time - pd.Timedelta(minutes=10))
                    & (kline_df["time"] <= exit_time + pd.Timedelta(minutes=10))
                ]

            if period.empty:
                skipped += 1
                continue

            # 计算
            result = _calc_max_floating_loss_from_klines(
                entry_price, exit_price, direction, entry_cost, leverage, period
            )

            if result["max_floating_loss_rate"] > 0:
                exceeded = 1 if result["max_floating_loss_rate"] > 0.10 else 0
                cursor.execute(
                    f"UPDATE {TABLE_TRADE_RECORDS} SET "
                    f"max_floating_loss = ?, max_floating_loss_rate = ?, exceeded_stoploss = ? "
                    f"WHERE trade_id = ?",
                    (
                        result["max_floating_loss"],
                        result["max_floating_loss_rate"],
                        exceeded,
                        trade["trade_id"],
                    ),
                )
                updated += 1
            else:
                skipped += 1

        conn.commit()

    except Exception as e:
        errors.append(str(e))
    finally:
        if own_conn:
            conn.close()

    return {"updated": updated, "skipped": skipped, "errors": errors}


def backfill_from_pkl(pkl_dir=None, conn: sqlite3.Connection = None) -> Dict[str, Any]:
    """
    从 pkl 文件补算 max_floating_loss（当数据库没有K线时使用）

    Returns:
        {"updated": 50, "skipped": 30, "errors": [...]}
    """
    pkl_dir = pkl_dir or PKL_DATA_DIR

    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    updated = 0
    skipped = 0
    errors = []

    try:
        # 加载pkl
        kline_data = load_all_pkl(pkl_dir)

        if not kline_data:
            return {"updated": 0, "skipped": 0, "errors": [], "message": "没有找到pkl文件"}

        # 读取需要补算的交易
        trades = pd.read_sql(
            f"SELECT * FROM {TABLE_TRADE_RECORDS} "
            f"WHERE (max_floating_loss_rate IS NULL OR max_floating_loss_rate = 0) "
            f"AND pnl IS NOT NULL "
            f"ORDER BY entry_time",
            conn,
        )

        if trades.empty:
            return {"updated": 0, "skipped": 0, "errors": [], "message": "没有需要补算的交易"}

        cursor = conn.cursor()

        for _, trade in trades.iterrows():
            symbol = trade["symbol"]
            entry_time = pd.to_datetime(trade["entry_time"])
            exit_time = pd.to_datetime(trade["exit_time"])
            entry_price = float(trade["entry_price"])
            exit_price = float(trade["exit_price"])
            direction = trade["direction"]
            entry_cost = float(trade["entry_cost"])
            leverage = int(trade["leverage"])

            # 查找K线
            kline_df = None
            for k, v in kline_data.items():
                if symbol.startswith(k) or k.startswith(symbol.split("-")[0]):
                    kline_df = v
                    break

            if kline_df is None or "time" not in kline_df.columns:
                skipped += 1
                continue

            kline_df = kline_df.copy()
            kline_df["time"] = pd.to_datetime(kline_df["time"])

            period = kline_df[
                (kline_df["time"] >= entry_time) & (kline_df["time"] <= exit_time)
            ]

            if period.empty:
                skipped += 1
                continue

            result = _calc_max_floating_loss_from_klines(
                entry_price, exit_price, direction, entry_cost, leverage, period
            )

            if result["max_floating_loss_rate"] > 0:
                exceeded = 1 if result["max_floating_loss_rate"] > 0.10 else 0
                cursor.execute(
                    f"UPDATE {TABLE_TRADE_RECORDS} SET "
                    f"max_floating_loss = ?, max_floating_loss_rate = ?, exceeded_stoploss = ? "
                    f"WHERE trade_id = ?",
                    (
                        result["max_floating_loss"],
                        result["max_floating_loss_rate"],
                        exceeded,
                        trade["trade_id"],
                    ),
                )
                updated += 1
            else:
                skipped += 1

        conn.commit()

    except Exception as e:
        errors.append(str(e))
    finally:
        if own_conn:
            conn.close()

    return {"updated": updated, "skipped": skipped, "errors": errors}
