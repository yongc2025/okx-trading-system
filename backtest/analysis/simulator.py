"""
模拟交易引擎
- 基于 K 线逐 bar 回放
- 支持止盈/止损参数化
- 批量模拟与参数优化
"""
import sqlite3
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS
from backtest.data.loader import load_klines


@dataclass
class SimResult:
    """单笔交易模拟结果"""
    trade_id: str = ""
    symbol: str = ""
    direction: str = ""
    entry_time: str = ""
    entry_price: float = 0.0
    # 模拟结果
    trigger_type: str = ""       # "stoploss" / "takeprofit" / "timeout"
    trigger_time: str = ""       # 触发时间
    exit_price: float = 0.0      # 模拟平仓价
    simulated_pnl: float = 0.0   # 模拟盈亏
    hold_bars: int = 0           # 持仓 bar 数
    # 对比原始
    original_pnl: float = 0.0
    pnl_diff: float = 0.0        # simulated - original


@dataclass
class BatchResult:
    """批量模拟结果"""
    params: Tuple[float, float] = (0.0, 0.0)  # (stoploss_pct, takeprofit_pct)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    max_drawdown: float = 0.0
    avg_hold_bars: float = 0.0
    trigger_distribution: Dict = field(default_factory=dict)
    simulated_trades: List[SimResult] = field(default_factory=list)


class TradeSimulator:
    """单笔交易模拟器"""

    def __init__(self, trigger_priority="stoploss_first", slippage=0.0):
        """
        Args:
            trigger_priority: 同 bar 触发优先级 "stoploss_first" / "takeprofit_first" / "open_compare"
            slippage: 滑点比例
        """
        self.trigger_priority = trigger_priority
        self.slippage = slippage

    def simulate(self, entry_price: float, direction: str, entry_cost: float,
                 leverage: int, klines: pd.DataFrame,
                 stoploss_pct: float = 0.0, takeprofit_pct: float = 0.0,
                 trade_id: str = "", entry_time: str = "") -> SimResult:
        """
        模拟单笔交易

        Args:
            entry_price: 开仓价格
            direction: "long" / "short"
            entry_cost: 开仓成本 (USDT)
            leverage: 杠杆倍数
            klines: K 线 DataFrame (time, open, high, low, close)
            stoploss_pct: 止损比例 (0.10 = 10%)，0 表示不设止损
            takeprofit_pct: 止盈比例 (0.20 = 20%)，0 表示不设止盈

        Returns:
            SimResult
        """
        if klines.empty:
            return SimResult(trigger_type="no_data", trade_id=trade_id)

        result = SimResult(
            trade_id=trade_id,
            entry_time=entry_time,
            entry_price=entry_price,
            direction=direction,
        )

        # 计算触发价
        if direction == "long":
            sl_price = entry_price * (1 - stoploss_pct) if stoploss_pct > 0 else None
            tp_price = entry_price * (1 + takeprofit_pct) if takeprofit_pct > 0 else None
        else:  # short
            sl_price = entry_price * (1 + stoploss_pct) if stoploss_pct > 0 else None
            tp_price = entry_price * (1 - takeprofit_pct) if takeprofit_pct > 0 else None

        # 逐 bar 回放
        for i, row in klines.iterrows():
            bar_open = float(row['open'])
            bar_high = float(row['high'])
            bar_low = float(row['low'])
            bar_close = float(row['close'])
            bar_time = str(row.get('time', ''))

            sl_triggered = False
            tp_triggered = False

            if direction == "long":
                if sl_price is not None and bar_low <= sl_price:
                    sl_triggered = True
                if tp_price is not None and bar_high >= tp_price:
                    tp_triggered = True
            else:
                if sl_price is not None and bar_high >= sl_price:
                    sl_triggered = True
                if tp_price is not None and bar_low <= tp_price:
                    tp_triggered = True

            if sl_triggered or tp_triggered:
                # 判断优先级
                if sl_triggered and tp_triggered:
                    if self.trigger_priority == "stoploss_first":
                        trigger_type = "stoploss"
                        exit_price = sl_price
                    elif self.trigger_priority == "takeprofit_first":
                        trigger_type = "takeprofit"
                        exit_price = tp_price
                    else:  # open_compare
                        if direction == "long":
                            if bar_open <= sl_price:
                                trigger_type = "stoploss"
                                exit_price = sl_price
                            else:
                                trigger_type = "takeprofit"
                                exit_price = tp_price
                        else:
                            if bar_open >= sl_price:
                                trigger_type = "stoploss"
                                exit_price = sl_price
                            else:
                                trigger_type = "takeprofit"
                                exit_price = tp_price
                elif sl_triggered:
                    trigger_type = "stoploss"
                    exit_price = sl_price
                else:
                    trigger_type = "takeprofit"
                    exit_price = tp_price

                # 应用滑点
                if self.slippage > 0:
                    if (direction == "long" and trigger_type == "stoploss") or \
                       (direction == "short" and trigger_type == "stoploss"):
                        exit_price = exit_price * (1 - self.slippage)
                    else:
                        exit_price = exit_price * (1 + self.slippage)

                # 计算盈亏
                qty = entry_cost * leverage / entry_price
                if direction == "long":
                    pnl = (exit_price - entry_price) * qty / leverage
                else:
                    pnl = (entry_price - exit_price) * qty / leverage

                result.trigger_type = trigger_type
                result.trigger_time = bar_time
                result.exit_price = round(exit_price, 6)
                result.simulated_pnl = round(pnl, 2)
                result.hold_bars = i  # bar 索引作为持仓 bar 数
                return result

        # 没触发 → 超时平仓（最后一根 bar 的 close）
        last_row = klines.iloc[-1]
        exit_price = float(last_row['close'])
        qty = entry_cost * leverage / entry_price
        if direction == "long":
            pnl = (exit_price - entry_price) * qty / leverage
        else:
            pnl = (entry_price - exit_price) * qty / leverage

        result.trigger_type = "timeout"
        result.trigger_time = str(last_row.get('time', ''))
        result.exit_price = round(exit_price, 6)
        result.simulated_pnl = round(pnl, 2)
        result.hold_bars = len(klines)
        return result


class BatchSimulator:
    """批量模拟器"""

    def __init__(self, kline_bar="5m", trigger_priority="stoploss_first", slippage=0.0):
        self.kline_bar = kline_bar
        self.simulator = TradeSimulator(trigger_priority, slippage)

    def run(self, trades_df: pd.DataFrame, stoploss_pct: float = 0.10,
            takeprofit_pct: float = 0.20) -> BatchResult:
        """
        对所有交易进行批量模拟

        Args:
            trades_df: 交易记录 DataFrame
            stoploss_pct: 止损比例
            takeprofit_pct: 止盈比例
        """
        closed = trades_df[trades_df['pnl'].notna()].copy()
        if closed.empty:
            return BatchResult(params=(stoploss_pct, takeprofit_pct))

        # 预加载所有涉及币种的 K 线到内存，避免 N+1 查询
        symbols = closed['symbol'].unique()
        kline_cache: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                kline_cache[sym] = load_klines(sym, self.kline_bar, source="auto")
            except Exception:
                kline_cache[sym] = pd.DataFrame()

        results = []
        for _, row in closed.iterrows():
            symbol = row.get('symbol', '')
            entry_time = row.get('entry_time', '')
            entry_price = float(row.get('entry_price', 0))
            direction = row.get('direction', 'long')
            leverage = int(row.get('leverage', 1))
            entry_cost = float(row.get('entry_cost', 1000))

            if not symbol or not entry_time or entry_price <= 0:
                continue

            # 从缓存中截取该笔交易之后的 K 线
            full_klines = kline_cache.get(symbol, pd.DataFrame())
            if full_klines.empty:
                continue

            klines = full_klines
            if 'time' in klines.columns and entry_time:
                klines = klines[klines['time'] >= pd.to_datetime(entry_time)]
            if klines.empty:
                continue

            sim = self.simulator.simulate(
                entry_price=entry_price,
                direction=direction,
                entry_cost=entry_cost,
                leverage=leverage,
                klines=klines,
                stoploss_pct=stoploss_pct,
                takeprofit_pct=takeprofit_pct,
                trade_id=row.get('trade_id', ''),
                entry_time=entry_time,
            )
            sim.original_pnl = float(row.get('pnl', 0))
            sim.pnl_diff = sim.simulated_pnl - sim.original_pnl
            sim.symbol = symbol
            results.append(sim)

        return self._aggregate(results, stoploss_pct, takeprofit_pct)

    def run_param_grid(self, trades_df: pd.DataFrame,
                       stoploss_ratios: list = None,
                       takeprofit_ratios: list = None) -> Dict[Tuple[float, float], BatchResult]:
        """
        参数网格搜索

        Returns:
            {(sl, tp): BatchResult}
        """
        stoploss_ratios = stoploss_ratios or [0.05, 0.10, 0.15, 0.20]
        takeprofit_ratios = takeprofit_ratios or [0.05, 0.10, 0.20, 0.50, 0.0]

        results = {}
        for sl in stoploss_ratios:
            for tp in takeprofit_ratios:
                if sl == 0 and tp == 0:
                    continue  # 跳过无止盈无止损
                batch = self.run(trades_df, stoploss_pct=sl, takeprofit_pct=tp)
                results[(sl, tp)] = batch

        return results

    def _aggregate(self, results: List[SimResult], sl: float, tp: float) -> BatchResult:
        """聚合模拟结果"""
        if not results:
            return BatchResult(params=(sl, tp))

        total = len(results)
        wins = sum(1 for r in results if r.simulated_pnl > 0)
        losses = sum(1 for r in results if r.simulated_pnl < 0)
        timeouts = sum(1 for r in results if r.trigger_type == "timeout")

        pnl_values = [r.simulated_pnl for r in results]
        total_pnl = sum(pnl_values)
        avg_pnl = total_pnl / total

        win_pnl = [p for p in pnl_values if p > 0]
        loss_pnl = [p for p in pnl_values if p < 0]
        avg_win = np.mean(win_pnl) if win_pnl else 0
        avg_loss = np.mean(loss_pnl) if loss_pnl else 0
        plr = abs(avg_win / avg_loss) if avg_loss != 0 else 9999.99

        # 最大回撤
        cum = np.cumsum(pnl_values)
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        max_dd = float(np.min(dd)) if len(dd) > 0 else 0

        # 触发分布
        trigger_dist = {}
        for r in results:
            trigger_dist[r.trigger_type] = trigger_dist.get(r.trigger_type, 0) + 1

        avg_bars = np.mean([r.hold_bars for r in results])

        batch = BatchResult(
            params=(sl, tp),
            total_trades=total,
            wins=wins,
            losses=losses,
            timeouts=timeouts,
            win_rate=round(wins / total, 4) if total > 0 else 0,
            profit_loss_ratio=round(plr, 2),
            total_pnl=round(total_pnl, 2),
            avg_pnl=round(avg_pnl, 2),
            max_drawdown=round(max_dd, 2),
            avg_hold_bars=round(float(avg_bars), 1),
            trigger_distribution=trigger_dist,
            simulated_trades=results,
        )
        return batch


def get_stoploss_comparison_from_sim(trades_df: pd.DataFrame,
                                      stoploss_ratios: list = None,
                                      kline_bar: str = "5m") -> Dict[str, Any]:
    """
    用模拟引擎重做止损对比（替代旧的 stoploss_sim.py 的简单截断逻辑）

    Returns:
        与旧版 stoploss_sim.py 接口兼容的格式
    """
    stoploss_ratios = stoploss_ratios or [0.05, 0.10, 0.15, 0.20]
    sim = BatchSimulator(kline_bar=kline_bar)

    comparison = []
    curves = {}

    # 实际结果
    closed = trades_df[trades_df['pnl'].notna()]
    if not closed.empty:
        total = len(closed)
        wins = int(closed['is_win'].sum()) if 'is_win' in closed.columns else 0
        total_pnl = float(closed['pnl'].sum())
        comparison.append({
            "stoploss_pct": "实际结果",
            "total_trades": total,
            "wins": wins,
            "win_rate": round(wins / total, 4),
            "total_pnl": round(total_pnl, 2),
        })

    # 各止损比例
    for ratio in stoploss_ratios:
        batch = sim.run(trades_df, stoploss_pct=ratio, takeprofit_pct=0)
        comparison.append({
            "stoploss_pct": f"{ratio*100:.0f}%",
            "total_trades": batch.total_trades,
            "wins": batch.wins,
            "losses": batch.losses,
            "win_rate": batch.win_rate,
            "win_rate_pct": f"{batch.win_rate * 100:.2f}%",
            "total_pnl": batch.total_pnl,
            "avg_pnl": batch.avg_pnl,
            "profit_loss_ratio": batch.profit_loss_ratio,
            "max_drawdown": batch.max_drawdown,
            "timeouts": batch.timeouts,
            "trigger_distribution": batch.trigger_distribution,
        })

    return {"comparison": comparison, "stoploss_ratios": [f"{r*100:.0f}%" for r in stoploss_ratios]}
