"""
扛单行为分析 (BT-03)
- 每笔亏损交易的最大浮亏计算
- 平均最大浮亏比率
- 超止损线标注
- 散点图 / 柱状图数据输出
"""
import sqlite3
from typing import Dict, Any, List

import numpy as np
import pandas as pd

from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS


def calc_holding_loss_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """
    扛单行为分析

    Args:
        df: 交易记录 DataFrame

    Returns:
        扛单分析结果
    """
    if df.empty or 'pnl' not in df.columns:
        return {"error": "无交易数据"}

    closed = df[df['pnl'].notna()].copy()
    if closed.empty:
        return {"error": "无交易数据"}

    # 只看亏损交易
    loss_trades = closed[closed['pnl'] < 0].copy()
    if loss_trades.empty:
        return {
            "total_loss_trades": 0,
            "message": "无亏损交易，不存在扛单行为",
        }

    total_loss_trades = len(loss_trades)

    # ---- 最大浮亏统计
    max_floating_loss = loss_trades['max_floating_loss']
    max_floating_loss_rate = loss_trades['max_floating_loss_rate']

    # 有效值（非零）
    valid_loss = max_floating_loss[max_floating_loss < 0]
    valid_loss_rate = max_floating_loss_rate[max_floating_loss_rate > 0]

    avg_max_floating_loss = float(valid_loss.mean()) if len(valid_loss) > 0 else 0
    avg_max_floating_loss_rate = float(valid_loss_rate.mean()) if len(valid_loss_rate) > 0 else 0

    # ---- 超止损线统计（默认止损线 10%）
    stoploss_threshold = 0.10
    exceeded = loss_trades[loss_trades['max_floating_loss_rate'] > stoploss_threshold]
    not_exceeded = loss_trades[loss_trades['max_floating_loss_rate'] <= stoploss_threshold]

    exceeded_count = len(exceeded)
    not_exceeded_count = len(not_exceeded)
    exceeded_ratio = exceeded_count / total_loss_trades if total_loss_trades > 0 else 0

    # ---- 扛单严重程度分级
    severity_bins = [0, 0.05, 0.10, 0.20, 0.50, float('inf')]
    severity_labels = ['<5%', '5-10%', '10-20%', '20-50%', '>50%']
    loss_trades_copy = loss_trades.copy()
    loss_trades_copy['severity'] = pd.cut(
        loss_trades_copy['max_floating_loss_rate'],
        bins=severity_bins,
        labels=severity_labels,
        right=False,
    )
    severity_dist = loss_trades_copy['severity'].value_counts().sort_index()
    severity_dict = {str(k): int(v) for k, v in severity_dist.items()}

    # ---- 散点图数据：每笔亏损交易的最大浮亏 vs 最终亏损
    scatter_data = []
    for _, row in loss_trades.iterrows():
        scatter_data.append({
            'trade_id': row.get('trade_id', ''),
            'symbol': row.get('symbol', ''),
            'entry_time': str(row.get('entry_time', '')),
            'max_floating_loss': round(float(row['max_floating_loss']), 2),
            'max_floating_loss_rate': round(float(row['max_floating_loss_rate']), 4),
            'final_pnl': round(float(row['pnl']), 2),
            'final_pnl_rate': round(float(row.get('pnl_rate', 0)), 4),
            'direction': row.get('direction', ''),
            'leverage': int(row.get('leverage', 1)),
            'exceeded_stoploss': int(row.get('exceeded_stoploss', 0)),
        })

    # ---- 按币种统计扛单
    symbol_holding = loss_trades.groupby('symbol').agg(
        loss_count=('pnl', 'count'),
        avg_max_floating_loss_rate=('max_floating_loss_rate', 'mean'),
        max_max_floating_loss_rate=('max_floating_loss_rate', 'max'),
        exceeded_count=('exceeded_stoploss', 'sum'),
        total_loss_amount=('pnl', 'sum'),
    ).reset_index()
    symbol_holding = symbol_holding.sort_values('avg_max_floating_loss_rate', ascending=False)

    # ---- 扛单 vs 非扛单对比
    # 扛单：最大浮亏超过止损线
    hold_loss_trades = loss_trades[loss_trades['max_floating_loss_rate'] > stoploss_threshold]
    no_hold_loss_trades = loss_trades[loss_trades['max_floating_loss_rate'] <= stoploss_threshold]

    comparison = {
        "holding": {
            "count": len(hold_loss_trades),
            "avg_final_loss": round(float(hold_loss_trades['pnl'].mean()), 2) if len(hold_loss_trades) > 0 else 0,
            "avg_max_floating_loss_rate": round(float(hold_loss_trades['max_floating_loss_rate'].mean()), 4) if len(hold_loss_trades) > 0 else 0,
        },
        "no_holding": {
            "count": len(no_hold_loss_trades),
            "avg_final_loss": round(float(no_hold_loss_trades['pnl'].mean()), 2) if len(no_hold_loss_trades) > 0 else 0,
            "avg_max_floating_loss_rate": round(float(no_hold_loss_trades['max_floating_loss_rate'].mean()), 4) if len(no_hold_loss_trades) > 0 else 0,
        },
    }

    return {
        "total_loss_trades": total_loss_trades,
        "avg_max_floating_loss": round(avg_max_floating_loss, 2),
        "avg_max_floating_loss_rate": round(avg_max_floating_loss_rate, 4),
        "avg_max_floating_loss_rate_pct": f"{avg_max_floating_loss_rate * 100:.2f}%",
        "stoploss_threshold": stoploss_threshold,
        "stoploss_threshold_pct": f"{stoploss_threshold * 100:.0f}%",
        "exceeded_stoploss_count": exceeded_count,
        "exceeded_stoploss_ratio": round(exceeded_ratio, 4),
        "exceeded_stoploss_ratio_pct": f"{exceeded_ratio * 100:.2f}%",
        "severity_distribution": severity_dict,
        "comparison": comparison,
        "symbol_holding_stats": symbol_holding.to_dict('records'),
        "scatter_data": scatter_data,
    }


def get_holding_loss_analysis(conn: sqlite3.Connection = None, account_id: str = None) -> Dict[str, Any]:
    """从数据库加载数据并执行扛单分析"""
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

    return calc_holding_loss_analysis(df)
