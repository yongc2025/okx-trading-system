"""
订单多维分析模块
供 /api/orders/analysis 接口使用
"""
import sqlite3
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

from backtest.config import TABLE_TRADE_RECORDS
from backtest.data.schema import get_connection


def get_order_analysis(account_id: str = None) -> dict:
    """
    返回订单多维分析结果

    Returns:
        {
            "hold_duration": {...},
            "time_heatmap": {...},
            "sequence": {...},
        }
    """
    conn = get_connection()
    try:
        sql = f"SELECT * FROM {TABLE_TRADE_RECORDS}"
        params = []
        if account_id:
            sql += " WHERE account_id = ?"
            params.append(account_id)
        sql += " ORDER BY entry_time"
        df = pd.read_sql(sql, conn, params=params if params else None)
    finally:
        conn.close()

    if df.empty:
        return {
            "hold_duration": {"error": "无数据"},
            "time_heatmap": {"error": "无数据"},
            "sequence": {"error": "无数据"},
        }

    # 解析时间
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["entry_time"])

    return {
        "hold_duration": _calc_hold_duration(df),
        "time_heatmap": _calc_time_heatmap(df),
        "sequence": _calc_sequence(df),
    }


# ---------------------------------------------------------------------------
# 持仓时长分析
# ---------------------------------------------------------------------------

def _calc_hold_duration(df: pd.DataFrame) -> dict:
    """按持仓时长分桶统计"""
    df = df.copy()
    df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0
    df = df.dropna(subset=["hold_minutes"])
    df = df[df["hold_minutes"] >= 0]

    if df.empty:
        return {"bins": {}}

    # 分桶
    bins = {
        "ultra_short": (0, 15),
        "short": (15, 60),
        "medium": (60, 1440),
        "long": (1440, 10080),
        "ultra_long": (10080, float("inf")),
    }

    result = {}
    for label, (lo, hi) in bins.items():
        mask = (df["hold_minutes"] >= lo) & (df["hold_minutes"] < hi)
        subset = df[mask]
        if subset.empty:
            result[label] = {
                "count": 0,
                "win_rate_pct": "0%",
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "avg_hold_minutes": 0.0,
            }
            continue

        wins = subset["is_win"].sum() if "is_win" in subset.columns else (subset["pnl"] > 0).sum()
        count = len(subset)
        win_rate = wins / count * 100 if count > 0 else 0
        total_pnl = subset["pnl"].sum() if "pnl" in subset.columns else 0.0

        result[label] = {
            "count": count,
            "win_rate_pct": f"{win_rate:.1f}%",
            "total_pnl": round(float(total_pnl), 2),
            "avg_pnl": round(float(total_pnl / count), 2) if count > 0 else 0.0,
            "avg_hold_minutes": round(float(subset["hold_minutes"].mean()), 1),
        }

    return {"bins": result}


# ---------------------------------------------------------------------------
# 交易时间热力图
# ---------------------------------------------------------------------------

def _calc_time_heatmap(df: pd.DataFrame) -> dict:
    """计算 星期×小时 的交易频率和胜率热力图数据"""
    df = df.copy()
    df["weekday"] = df["entry_time"].dt.weekday  # 0=周一
    df["hour"] = df["entry_time"].dt.hour

    frequency = []
    winrate = []

    for wd in range(7):
        for hr in range(24):
            mask = (df["weekday"] == wd) & (df["hour"] == hr)
            subset = df[mask]
            count = len(subset)
            frequency.append([wd, hr, count])

            if count > 0 and "is_win" in subset.columns:
                wr = float(subset["is_win"].mean())
            else:
                wr = 0
            winrate.append([wd, hr, round(wr, 3)])

    return {"frequency": frequency, "winrate": winrate}


# ---------------------------------------------------------------------------
# 序列分析（连胜/连亏/回撤）
# ---------------------------------------------------------------------------

def _calc_sequence(df: pd.DataFrame) -> dict:
    """计算连胜连亏序列和最大回撤"""
    if "pnl" not in df.columns:
        return {"error": "缺少 pnl 列"}

    pnls = df["pnl"].dropna().tolist()
    if not pnls:
        return {"error": "无数据"}

    # 连胜/连亏序列
    streaks = []
    current_type = None  # 'win' or 'loss'
    current_count = 0

    for pnl in pnls:
        result = "win" if pnl > 0 else "loss"
        if result == current_type:
            current_count += 1
        else:
            if current_type is not None:
                streaks.append((current_type, current_count))
            current_type = result
            current_count = 1
    if current_type is not None:
        streaks.append((current_type, current_count))

    # 序列分布
    streak_dist = defaultdict(int)
    for stype, count in streaks:
        key = f"{stype}_{count}"
        streak_dist[key] += 1

    # 最大回撤（基于累计净值）
    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    drawdowns = running_max - cum
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    return {
        "max_drawdown": round(max_dd, 2),
        "total_streaks": len(streaks),
        "streak_distribution": dict(streak_dist),
    }
