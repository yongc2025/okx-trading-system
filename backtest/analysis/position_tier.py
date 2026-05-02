"""
仓位策略分层分析 (BT-05)
- 首仓独立统计 vs 加仓后整体统计
- 加仓次数分布
- 对比图数据
"""
import math
import sqlite3
from typing import Dict, Any

import numpy as np
import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS


def _empty_tier_stats(label: str) -> Dict[str, Any]:
    """空分组的默认统计值，确保前端不会拿到 undefined"""
    return {
        "label": label,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "win_rate_pct": "0.00%",
        "total_pnl": 0,
        "avg_pnl": 0,
        "avg_win": 0,
        "avg_loss": 0,
        "profit_loss_ratio": 0,
        "stoploss_triggered": 0,
        "stoploss_ratio": 0,
        "stoploss_ratio_pct": "0.00%",
        "avg_max_floating_loss_rate": 0,
    }


def _calc_tier_stats(df: pd.DataFrame, label: str) -> Dict[str, Any]:
    """计算单组交易的统计指标"""
    if df.empty:
        return _empty_tier_stats(label)

    total = len(df)
    wins = int(df['is_win'].sum()) if 'is_win' in df.columns else 0
    losses = int(df['is_loss'].sum()) if 'is_loss' in df.columns else 0
    win_rate = wins / total if total > 0 else 0

    pnl_values = df['pnl'].dropna()
    total_pnl = float(pnl_values.sum()) if len(pnl_values) > 0 else 0
    avg_pnl = float(pnl_values.mean()) if len(pnl_values) > 0 else 0

    win_trades = pnl_values[pnl_values > 0]
    loss_trades = pnl_values[pnl_values < 0]

    avg_win = float(win_trades.mean()) if len(win_trades) > 0 else 0
    avg_loss = float(loss_trades.mean()) if len(loss_trades) > 0 else 0
    if avg_loss != 0:
        profit_loss_ratio = abs(avg_win / avg_loss)
        if math.isinf(profit_loss_ratio) or math.isnan(profit_loss_ratio):
            profit_loss_ratio = 0
    else:
        profit_loss_ratio = 0

    # 止损触发
    stoploss_triggered = int(df['exceeded_stoploss'].sum()) if 'exceeded_stoploss' in df.columns else 0
    stoploss_ratio = stoploss_triggered / total if total > 0 else 0

    # 最大浮亏
    avg_max_floating_loss_rate = float(df['max_floating_loss_rate'].mean()) if 'max_floating_loss_rate' in df.columns else 0

    return {
        "label": label,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "win_rate_pct": f"{win_rate * 100:.2f}%",
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "stoploss_triggered": stoploss_triggered,
        "stoploss_ratio": round(stoploss_ratio, 4),
        "stoploss_ratio_pct": f"{stoploss_ratio * 100:.2f}%",
        "avg_max_floating_loss_rate": round(avg_max_floating_loss_rate, 4),
    }


def analyze_position_tiers(df: pd.DataFrame) -> Dict[str, Any]:
    """
    仓位策略分层分析

    分为：
    1. 首仓独立统计（position_tier == 'first'）
    2. 第一次加仓（position_tier == 'add1'）
    3. 第二次加仓（position_tier == 'add2'）
    4. 加仓后整体（add1 + add2）
    5. 全部交易
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {"error": "无交易数据"}

    # 确保 position_tier 列存在
    if 'position_tier' not in closed.columns:
        closed['position_tier'] = 'first'

    # 填充缺失值
    closed['position_tier'] = closed['position_tier'].fillna('first')

    # ---- 分层统计
    first_only = closed[closed['position_tier'] == 'first']
    add1_only = closed[closed['position_tier'] == 'add1']
    add2_only = closed[closed['position_tier'] == 'add2']
    all_add = closed[closed['position_tier'].isin(['add1', 'add2'])]

    stats_first = _calc_tier_stats(first_only, "首仓 (50%)")
    stats_add1 = _calc_tier_stats(add1_only, "第一次加仓 (25%)")
    stats_add2 = _calc_tier_stats(add2_only, "第二次加仓 (25%)")
    stats_all_add = _calc_tier_stats(all_add, "加仓后整体")
    stats_total = _calc_tier_stats(closed, "全部交易")

    # ---- 加仓次数分布
    # 按 symbol 分组，看每组有多少次加仓
    tier_dist = closed.groupby('position_tier').size().to_dict()
    tier_dist = {str(k): int(v) for k, v in tier_dist.items()}

    # 按币种统计加仓次数
    if 'symbol' in closed.columns:
        symbol_tiers = closed.groupby(['symbol', 'position_tier']).size().unstack(fill_value=0)
        symbol_tier_counts = {}
        for sym in symbol_tiers.index:
            first_c = int(symbol_tiers.loc[sym].get('first', 0))
            add1_c = int(symbol_tiers.loc[sym].get('add1', 0))
            add2_c = int(symbol_tiers.loc[sym].get('add2', 0))
            max_tier = 'first'
            if add2_c > 0:
                max_tier = 'add2'
            elif add1_c > 0:
                max_tier = 'add1'
            symbol_tier_counts[sym] = {
                'first': first_c,
                'add1': add1_c,
                'add2': add2_c,
                'max_tier': max_tier,
            }

        # 加仓完成度分布
        completion_dist = {}
        for sym, info in symbol_tier_counts.items():
            tier = info['max_tier']
            completion_dist[tier] = completion_dist.get(tier, 0) + 1
    else:
        symbol_tier_counts = {}
        completion_dist = {}

    # ---- 对比：首仓 vs 加仓后
    comparison = {
        "first_position": stats_first,
        "after_add": stats_all_add,
        "improvement": {
            "win_rate_diff": round(stats_all_add.get('win_rate', 0) - stats_first.get('win_rate', 0), 4),
            "avg_pnl_diff": round(stats_all_add.get('avg_pnl', 0) - stats_first.get('avg_pnl', 0), 2),
            "profit_loss_ratio_diff": round(
                stats_all_add.get('profit_loss_ratio', 0) - stats_first.get('profit_loss_ratio', 0), 2
            ),
        },
    }

    return {
        "first_position": stats_first,
        "add1": stats_add1,
        "add2": stats_add2,
        "after_add": stats_all_add,
        "total": stats_total,
        "tier_distribution": tier_dist,
        "completion_distribution": completion_dist,
        "comparison": comparison,
    }


def get_position_tier_analysis(conn: sqlite3.Connection = None, account_id: str = None) -> Dict[str, Any]:
    """从数据库加载数据并执行仓位分层分析"""
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

    return analyze_position_tiers(df)
