"""
基础交易统计分析 (BT-02)
- 胜率 / 盈亏比 / 总交易笔数
- 累计收益率曲线（净值曲线）
- 最大连续盈利 / 亏损
- 盈亏分布统计
"""
import sqlite3
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS


def calc_basic_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算基础交易统计指标

    Args:
        df: 交易记录 DataFrame（需包含 pnl, is_win, is_loss 列）

    Returns:
        统计指标字典
    """
    if df.empty:
        return {"error": "无交易数据"}

    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {"error": "无已平仓交易"}

    total = len(closed)
    wins = closed['is_win'].sum()
    losses = closed['is_loss'].sum()
    breakeven = total - wins - losses

    # 胜率
    win_rate = wins / total if total > 0 else 0

    # 盈亏金额
    total_pnl = closed['pnl'].sum()
    avg_pnl = closed['pnl'].mean()

    # 盈利/亏损平均
    win_trades = closed[closed['pnl'] > 0]
    loss_trades = closed[closed['pnl'] < 0]

    avg_win = win_trades['pnl'].mean() if len(win_trades) > 0 else 0
    avg_loss = loss_trades['pnl'].mean() if len(loss_trades) > 0 else 0

    # 盈亏比
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    # 最大单笔盈利/亏损
    max_win = closed['pnl'].max()
    max_loss = closed['pnl'].min()

    # 总盈利/总亏损
    total_win_amount = win_trades['pnl'].sum() if len(win_trades) > 0 else 0
    total_loss_amount = loss_trades['pnl'].sum() if len(loss_trades) > 0 else 0

    # 期望值（每笔交易的预期收益）
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    return {
        "total_trades": total,
        "wins": int(wins),
        "losses": int(losses),
        "breakeven": int(breakeven),
        "win_rate": round(win_rate, 4),
        "win_rate_pct": f"{win_rate * 100:.2f}%",
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
        "total_win_amount": round(total_win_amount, 2),
        "total_loss_amount": round(total_loss_amount, 2),
        "expectancy": round(expectancy, 2),
    }


def calc_consecutive_streaks(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算最大连续盈利/亏损

    Args:
        df: 交易记录 DataFrame

    Returns:
        连续统计字典
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {"max_consecutive_wins": 0, "max_consecutive_losses": 0}

    # 按时间排序
    closed = closed.sort_values('entry_time')

    # 计算连续
    max_win_streak = 0
    max_loss_streak = 0
    current_win_streak = 0
    current_loss_streak = 0

    for _, row in closed.iterrows():
        if row['pnl'] > 0:
            current_win_streak += 1
            current_loss_streak = 0
            max_win_streak = max(max_win_streak, current_win_streak)
        elif row['pnl'] < 0:
            current_loss_streak += 1
            current_win_streak = 0
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        else:
            current_win_streak = 0
            current_loss_streak = 0

    return {
        "max_consecutive_wins": max_win_streak,
        "max_consecutive_losses": max_loss_streak,
        "current_streak": current_win_streak if current_win_streak > 0 else -current_loss_streak,
    }


def calc_equity_curve(df: pd.DataFrame, initial_capital: float = None) -> pd.DataFrame:
    """
    计算累计收益曲线（净值曲线）

    Args:
        df: 交易记录 DataFrame
        initial_capital: 初始资金（默认取第一笔交易的 account_capital）

    Returns:
        DataFrame: time, pnl, cumulative_pnl, equity, roi
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return pd.DataFrame()

    closed = closed.sort_values('entry_time')

    if initial_capital is None:
        initial_capital = closed.iloc[0].get('account_capital', 10000)
        if pd.isna(initial_capital) or initial_capital <= 0:
            initial_capital = 10000

    result = pd.DataFrame({
        'time': closed['entry_time'],
        'symbol': closed['symbol'],
        'direction': closed['direction'],
        'pnl': closed['pnl'].values,
        'trade_id': closed['trade_id'].values,
    })

    result['cumulative_pnl'] = result['pnl'].cumsum()
    result['equity'] = initial_capital + result['cumulative_pnl']
    result['roi'] = result['cumulative_pnl'] / initial_capital
    result['drawdown'] = result['equity'] / result['equity'].cummax() - 1

    return result.reset_index(drop=True)


def calc_pnl_distribution(df: pd.DataFrame, bins: int = 20) -> Dict[str, Any]:
    """
    盈亏分布统计

    Args:
        df: 交易记录 DataFrame
        bins: 分组数

    Returns:
        分布数据
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {"bins": [], "counts": []}

    pnl_values = closed['pnl'].values

    # 分组
    hist, bin_edges = np.histogram(pnl_values, bins=bins)
    bin_labels = [f"{bin_edges[i]:.0f} ~ {bin_edges[i+1]:.0f}" for i in range(len(hist))]

    return {
        "bins": bin_labels,
        "counts": hist.tolist(),
        "mean": round(float(np.mean(pnl_values)), 2),
        "median": round(float(np.median(pnl_values)), 2),
        "std": round(float(np.std(pnl_values)), 2),
        "skewness": round(float(pd.Series(pnl_values).skew()), 4),
        "kurtosis": round(float(pd.Series(pnl_values).kurtosis()), 4),
    }


def calc_monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    按月统计交易表现

    Returns:
        DataFrame: month, trades, wins, losses, win_rate, total_pnl, avg_pnl
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return pd.DataFrame()

    closed = closed.copy()
    closed['month'] = pd.to_datetime(closed['entry_time']).dt.to_period('M').astype(str)

    monthly = closed.groupby('month').agg(
        trades=('pnl', 'count'),
        wins=('is_win', 'sum'),
        losses=('is_loss', 'sum'),
        total_pnl=('pnl', 'sum'),
        avg_pnl=('pnl', 'mean'),
        max_win=('pnl', 'max'),
        max_loss=('pnl', 'min'),
    ).reset_index()

    monthly['win_rate'] = (monthly['wins'] / monthly['trades']).round(4)

    return monthly


def calc_symbol_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    按币种统计交易表现

    Returns:
        DataFrame: symbol, trades, wins, losses, win_rate, total_pnl, avg_pnl
    """
    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return pd.DataFrame()

    sym_stats = closed.groupby('symbol').agg(
        trades=('pnl', 'count'),
        wins=('is_win', 'sum'),
        losses=('is_loss', 'sum'),
        total_pnl=('pnl', 'sum'),
        avg_pnl=('pnl', 'mean'),
        max_win=('pnl', 'max'),
        max_loss=('pnl', 'min'),
    ).reset_index()

    sym_stats['win_rate'] = (sym_stats['wins'] / sym_stats['trades']).round(4)
    sym_stats = sym_stats.sort_values('total_pnl', ascending=False)

    return sym_stats


def get_full_analysis(conn: sqlite3.Connection = None) -> Dict[str, Any]:
    """
    获取完整的分析结果

    Returns:
        包含所有分析指标的字典
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    df = pd.read_sql(f"SELECT * FROM {TABLE_TRADE_RECORDS} ORDER BY entry_time", conn)

    if own_conn:
        conn.close()

    result = {
        "basic_stats": calc_basic_stats(df),
        "consecutive": calc_consecutive_streaks(df),
        "equity_curve": calc_equity_curve(df),
        "pnl_distribution": calc_pnl_distribution(df),
        "monthly_stats": calc_monthly_stats(df),
        "symbol_stats": calc_symbol_stats(df),
    }

    return result
