"""
止损回测模拟 (BT-04)
- 多止损比例并行对比（5% / 10% / 15% / 20%）
- 模拟盈亏重算
- 对比表格（胜率 / 总盈亏 / 盈亏比）
- 多线收益曲线对比数据
"""
import math
import sqlite3
from typing import Dict, Any, List

import numpy as np
import pandas as pd

from backtest.config import DEFAULT_STOPLOSS_RATIOS
from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS


def simulate_stoploss_for_trade(
    row: pd.Series,
    stoploss_ratio: float,
) -> Dict[str, Any]:
    """
    对单笔交易模拟止损

    如果实际亏损比率超过设定止损比例，则替换为止损点的亏损额；
    否则保留原始结果。

    Args:
        row: 单笔交易记录
        stoploss_ratio: 止损比例 (如 0.10 表示 10%)，0 表示实际结果不模拟

    Returns:
        模拟后的交易数据
    """
    pnl = row['pnl']
    if pd.isna(pnl):
        return {
            'original_pnl': None,
            'simulated_pnl': None,
            'simulated': False,
        }

    original_pnl = float(pnl)

    # ratio=0 表示"实际结果"，直接返回原值，不做任何模拟
    if stoploss_ratio <= 0:
        return {
            'original_pnl': original_pnl,
            'simulated_pnl': original_pnl,
            'simulated': False,
            'pnl_diff': 0,
        }

    entry_cost = float(row.get('entry_cost', 0))
    leverage = int(row.get('leverage', 1))
    direction = row.get('direction', 'long')

    # 止损时的亏损额 = 本金 × 止损比例
    stoploss_pnl = -entry_cost * stoploss_ratio * leverage

    # 如果实际亏损超过止损线，替换为止损亏损
    if original_pnl < 0 and abs(original_pnl) > abs(stoploss_pnl):
        return {
            'original_pnl': original_pnl,
            'simulated_pnl': stoploss_pnl,
            'simulated': True,
            'pnl_diff': stoploss_pnl - original_pnl,  # 正数 = 减少亏损
        }

    # 未触发止损，保留原值
    return {
        'original_pnl': original_pnl,
        'simulated_pnl': original_pnl,
        'simulated': False,
        'pnl_diff': 0,
    }


def simulate_stoploss_batch(
    df: pd.DataFrame,
    stoploss_ratio: float,
) -> pd.DataFrame:
    """
    对所有交易批量模拟止损

    Returns:
        DataFrame: 包含模拟后的 pnl, is_win, is_loss
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return pd.DataFrame()

    results = []
    for _, row in closed.iterrows():
        sim = simulate_stoploss_for_trade(row, stoploss_ratio)
        results.append(sim)

    sim_df = pd.DataFrame(results)
    result = closed.copy()
    result['original_pnl'] = sim_df['original_pnl'].values
    result['simulated_pnl'] = sim_df['simulated_pnl'].values
    result['simulated'] = sim_df['simulated'].values
    result['pnl_diff'] = sim_df['pnl_diff'].values

    # 重算 is_win / is_loss
    result['pnl'] = result['simulated_pnl']
    result['is_win'] = (result['simulated_pnl'] > 0).astype(int)
    result['is_loss'] = (result['simulated_pnl'] < 0).astype(int)

    return result


def calc_stoploss_stats(df: pd.DataFrame, stoploss_ratio: float) -> Dict[str, Any]:
    """
    计算单个止损比例下的统计指标
    """
    sim_df = simulate_stoploss_batch(df, stoploss_ratio)
    if sim_df.empty:
        return {"stoploss_ratio": stoploss_ratio, "error": "无交易数据"}

    total = len(sim_df)
    wins = int(sim_df['is_win'].sum())
    losses = int(sim_df['is_loss'].sum())
    win_rate = wins / total if total > 0 else 0

    total_pnl = float(sim_df['simulated_pnl'].sum())
    avg_pnl = float(sim_df['simulated_pnl'].mean())

    win_trades = sim_df[sim_df['simulated_pnl'] > 0]
    loss_trades = sim_df[sim_df['simulated_pnl'] < 0]

    avg_win = float(win_trades['simulated_pnl'].mean()) if len(win_trades) > 0 else 0
    avg_loss = float(loss_trades['simulated_pnl'].mean()) if len(loss_trades) > 0 else 0
    if avg_loss != 0:
        profit_loss_ratio = abs(avg_win / avg_loss)
        if math.isinf(profit_loss_ratio) or math.isnan(profit_loss_ratio):
            profit_loss_ratio = 9999.99
    else:
        profit_loss_ratio = 9999.99  # 无亏损交易时用大数代替 inf

    # 被止损截断的交易数
    simulated_count = int(sim_df['simulated'].sum())
    pnl_saved = float(sim_df.loc[sim_df['simulated'], 'pnl_diff'].sum())

    return {
        "stoploss_ratio": stoploss_ratio,
        "stoploss_pct": f"{stoploss_ratio * 100:.0f}%",
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
        "simulated_count": simulated_count,
        "pnl_saved_by_stoploss": round(pnl_saved, 2),
    }


def calc_stoploss_comparison(
    df: pd.DataFrame,
    stoploss_ratios: List[float] = None,
) -> Dict[str, Any]:
    """
    多止损比例并行对比

    Args:
        df: 交易记录 DataFrame
        stoploss_ratios: 止损比例列表，默认 [5%, 10%, 15%, 20%]

    Returns:
        对比结果
    """
    stoploss_ratios = stoploss_ratios or DEFAULT_STOPLOSS_RATIOS

    # 原始结果
    original_stats = calc_stoploss_stats(df, 0.0)
    original_stats['stoploss_pct'] = '实际结果'

    # 各止损比例的结果
    comparison = [original_stats]
    for ratio in stoploss_ratios:
        stats = calc_stoploss_stats(df, ratio)
        comparison.append(stats)

    return {
        "comparison_table": comparison,
        "stoploss_ratios": ['实际结果'] + [f"{r*100:.0f}%" for r in stoploss_ratios],
    }


def calc_equity_curves_comparison(
    df: pd.DataFrame,
    stoploss_ratios: List[float] = None,
    initial_capital: float = None,
) -> Dict[str, pd.DataFrame]:
    """
    多止损比例下的收益曲线对比

    Returns:
        {label: DataFrame} 每个止损比例对应的净值曲线
    """
    stoploss_ratios = stoploss_ratios or DEFAULT_STOPLOSS_RATIOS

    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {}

    closed = closed.sort_values('entry_time')

    if initial_capital is None:
        initial_capital = closed.iloc[0].get('account_capital', 10000)
        if pd.isna(initial_capital) or initial_capital <= 0:
            initial_capital = 10000

    curves = {}

    # 原始曲线
    orig_pnl = closed['pnl'].values
    orig_cum = np.cumsum(orig_pnl)
    curves['实际结果'] = pd.DataFrame({
        'time': closed['entry_time'].values,
        'cumulative_pnl': orig_cum,
        'equity': initial_capital + orig_cum,
        'roi': orig_cum / initial_capital,
    })

    # 各止损比例曲线
    for ratio in stoploss_ratios:
        sim_df = simulate_stoploss_batch(closed, ratio)
        if sim_df.empty:
            continue
        sim_pnl = sim_df['simulated_pnl'].values
        sim_cum = np.cumsum(sim_pnl)
        label = f"{ratio*100:.0f}%止损"
        curves[label] = pd.DataFrame({
            'time': closed['entry_time'].values,
            'cumulative_pnl': sim_cum,
            'equity': initial_capital + sim_cum,
            'roi': sim_cum / initial_capital,
        })

    return curves


def _safe_float(v: float, default: float = 0.0) -> float:
    """将 inf/nan 替换为安全默认值，确保 JSON 可序列化"""
    if math.isinf(v) or math.isnan(v):
        return default
    return v


def get_stoploss_analysis(conn: sqlite3.Connection = None) -> Dict[str, Any]:
    """从数据库加载数据并执行止损回测分析"""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    df = pd.read_sql(f"SELECT * FROM {TABLE_TRADE_RECORDS} ORDER BY entry_time", conn)

    if own_conn:
        conn.close()

    comparison = calc_stoploss_comparison(df)
    curves = calc_equity_curves_comparison(df)

    # 序列化曲线数据（过滤 inf/nan）
    curves_data = {}
    for label, curve_df in curves.items():
        curves_data[label] = {
            'time': curve_df['time'].tolist(),
            'equity': [round(_safe_float(float(v)), 2) for v in curve_df['equity']],
            'roi': [round(_safe_float(float(v)), 4) for v in curve_df['roi']],
            'cumulative_pnl': [round(_safe_float(float(v)), 2) for v in curve_df['cumulative_pnl']],
        }

    return {
        "comparison": comparison,
        "equity_curves": curves_data,
    }
