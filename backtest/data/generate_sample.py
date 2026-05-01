"""
生成模拟测试数据
用于在没有真实 pkl 文件时测试整个回测系统
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.config import PKL_DATA_DIR, DATA_DIR


def generate_kline_data(
    symbol: str,
    start_price: float = 100.0,
    days: int = 90,
    interval_minutes: int = 60,
    volatility: float = 0.02,
    seed: int = None,
) -> pd.DataFrame:
    """
    生成单个币种的模拟 K 线数据

    Args:
        symbol: 币种名
        start_price: 起始价格
        days: 天数
        interval_minutes: K 线周期(分钟)
        volatility: 波动率
        seed: 随机种子
    """
    if seed is not None:
        np.random.seed(seed)

    periods = (days * 24 * 60) // interval_minutes
    times = [datetime(2025, 1, 1) + timedelta(minutes=i * interval_minutes) for i in range(periods)]

    # 几何布朗运动模拟价格
    returns = np.random.normal(0.0001, volatility, periods)

    # 偶尔插入极端行情（close-to-close）
    extreme_indices = np.random.choice(periods, size=max(1, periods // 500), replace=False)
    for idx in extreme_indices:
        returns[idx] = np.random.choice([-0.12, -0.15, 0.12, 0.15])

    prices = start_price * np.exp(np.cumsum(returns))

    # 生成 OHLCV
    opens = prices
    highs = opens * (1 + np.abs(np.random.normal(0, volatility / 2, periods)))
    lows = opens * (1 - np.abs(np.random.normal(0, volatility / 2, periods)))
    closes = opens * (1 + np.random.normal(0, volatility / 3, periods))
    volumes = np.random.exponential(1000, periods) * start_price

    # 注入几根极端 K 线（open-to-close 超过 10%，模拟插针/闪崩）
    num_extreme_candles = max(2, periods // 1000)
    extreme_candle_idx = np.random.choice(periods, size=num_extreme_candles, replace=False)
    for idx in extreme_candle_idx:
        direction = np.random.choice([-1, 1])
        magnitude = np.random.uniform(0.10, 0.20)
        candle_move = direction * magnitude
        opens[idx] = prices[idx]
        closes[idx] = prices[idx] * (1 + candle_move)
        if candle_move > 0:
            highs[idx] = closes[idx] * 1.005
            lows[idx] = opens[idx] * 0.995
        else:
            highs[idx] = opens[idx] * 1.005
            lows[idx] = closes[idx] * 0.995
        volumes[idx] *= 10  # 极端行情放量

    df = pd.DataFrame({
        'time': times,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'amount': volumes * closes,
    })

    return df


def generate_trade_records(
    kline_data: dict,
    num_trades: int = 200,
    initial_capital: float = 10000.0,
    seed: int = None,
) -> pd.DataFrame:
    """
    基于 K 线数据生成模拟交易记录

    Args:
        kline_data: {symbol: DataFrame} K 线数据
        num_trades: 交易笔数
        initial_capital: 初始资金
        seed: 随机种子
    """
    if seed is not None:
        np.random.seed(seed)

    symbols = list(kline_data.keys())
    if not symbols:
        return pd.DataFrame()

    records = []
    capital = initial_capital

    for i in range(num_trades):
        symbol = random.choice(symbols)
        df = kline_data[symbol]
        if len(df) < 10:
            continue

        # 随机选一个开仓点
        entry_idx = random.randint(0, len(df) - 10)
        entry_price = df.iloc[entry_idx]['close']
        direction = random.choice(['long', 'short'])
        leverage = random.choice([1, 2, 3])
        position_tier = random.choices(['first', 'add1', 'add2'], weights=[0.5, 0.3, 0.2])[0]

        # 仓位大小
        tier_pct = {'first': 0.50, 'add1': 0.25, 'add2': 0.25}[position_tier]
        entry_cost = capital * tier_pct
        entry_qty = entry_cost * leverage / entry_price

        # 随机持仓时间 1~50 根 K 线
        hold_bars = random.randint(1, min(50, len(df) - entry_idx - 1))
        exit_idx = entry_idx + hold_bars
        exit_price = df.iloc[exit_idx]['close']

        # 计算盈亏
        if direction == 'long':
            pnl = (exit_price - entry_price) / entry_price * entry_cost * leverage
        else:
            pnl = (entry_price - exit_price) / entry_price * entry_cost * leverage

        pnl_rate = pnl / capital
        roi = pnl / entry_cost
        is_win = 1 if pnl > 0 else 0
        is_loss = 1 if pnl < 0 else 0

        # 模拟最大浮亏
        if direction == 'long':
            min_price = df.iloc[entry_idx:exit_idx + 1]['low'].min()
            max_loss = (min_price - entry_price) / entry_price * entry_cost * leverage
        else:
            max_price = df.iloc[entry_idx:exit_idx + 1]['high'].max()
            max_loss = (entry_price - max_price) / entry_price * entry_cost * leverage

        max_floating_loss = min(max_loss, 0)
        max_floating_loss_rate = abs(max_floating_loss) / capital if max_floating_loss < 0 else 0

        entry_time = df.iloc[entry_idx]['time']
        exit_time = df.iloc[exit_idx]['time']

        # 构造持仓快照（BT-11 测试需要快照数 > 0）
        # 简单生成起止两个快照点
        snapshot_records = [
            {
                'trade_id': f"T{i+1:04d}",
                'symbol': symbol,
                'snapshot_time': entry_time.isoformat(),
                'price': entry_price,
                'floating_pnl': 0,
                'floating_pnl_rate': 0
            },
            {
                'trade_id': f"T{i+1:04d}",
                'symbol': symbol,
                'snapshot_time': exit_time.isoformat(),
                'price': exit_price,
                'floating_pnl': pnl,
                'floating_pnl_rate': roi
            }
        ]

        records.append({
            'trade_id': f"T{i+1:04d}",
            'symbol': symbol,
            'direction': direction,
            'leverage': leverage,
            'position_tier': position_tier,
            'entry_time': entry_time.isoformat() if hasattr(entry_time, 'isoformat') else str(entry_time),
            'entry_price': round(entry_price, 6),
            'entry_qty': round(entry_qty, 4),
            'entry_cost': round(entry_cost, 2),
            'exit_time': exit_time.isoformat() if hasattr(exit_time, 'isoformat') else str(exit_time),
            'exit_price': round(exit_price, 6),
            'exit_qty': round(entry_qty, 4),
            'exit_value': round(entry_qty * exit_price / leverage, 2),
            'pnl': round(pnl, 2),
            'pnl_rate': round(pnl_rate, 6),
            'roi': round(roi, 6),
            'is_win': is_win,
            'is_loss': is_loss,
            'max_floating_loss': round(max_floating_loss, 2),
            'max_floating_loss_rate': round(max_floating_loss_rate, 6),
            'exceeded_stoploss': 1 if max_floating_loss_rate > 0.10 else 0,
            'account_capital': round(capital, 2),
            'snapshots': snapshot_records # 携带快照数据
        })

        capital += pnl
        capital = max(capital, 100)  # 最低保留 100

    return pd.DataFrame(records)


def generate_sample_data(output_dir: Path = None, num_symbols: int = 20, days: int = 90, num_trades: int = 200, db_path: str = None):
    """
    生成完整的样本数据集

    Args:
        output_dir: 输出目录
        num_symbols: 生成币种数量
        days: K 线天数
        num_trades: 交易笔数
        db_path: (兼容性参数) 数据库路径，若提供则尝试导入数据库
    """
    output_dir = output_dir or PKL_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # 币种列表
    base_symbols = [
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC",
        "LINK", "UNI", "ATOM", "LTC", "ETC", "FIL", "APT", "ARB", "OP", "NEAR",
        "AAVE", "MKR", "SNX", "CRV", "COMP", "SUSHI", "YFI", "BAL", "RUNE", "INJ",
    ]
    symbols = [f"{s}-USDT" for s in base_symbols[:num_symbols]]

    print(f"🎲 生成 {num_symbols} 个币种的模拟 K 线数据 ({days} 天)...")

    # 生成 K 线数据
    kline_data = {}
    for i, symbol in enumerate(symbols):
        start_price = random.uniform(0.5, 50000)
        volatility = random.uniform(0.01, 0.04)
        df = generate_kline_data(symbol, start_price, days, volatility=volatility, seed=i)
        kline_data[symbol] = df
        print(f"  ✅ {symbol}: {len(df)} 条 K 线, 价格 {df['close'].iloc[0]:.4f} → {df['close'].iloc[-1]:.4f}")

    # 保存 K 线 pkl
    kline_path = output_dir / "sample_kline_data.pkl"
    pd.to_pickle(kline_data, str(kline_path))
    print(f"\n💾 K 线数据已保存: {kline_path} ({kline_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # 生成交易记录
    print(f"\n🎲 生成 {num_trades} 笔模拟交易记录...")
    trades_df = generate_trade_records(kline_data, num_trades=num_trades, seed=42)
    trades_path = output_dir / "sample_trades.pkl"
    pd.to_pickle(trades_df, str(trades_path))
    print(f"💾 交易记录已保存: {trades_path}")

    # 若提供了 db_path，则同步导入数据库
    if db_path:
        from backtest.data.import_data import import_trades_to_db, import_klines_to_db
        from backtest.data.schema import init_database
        init_database(db_path)
        import_trades_to_db(trades_df, db_path)
        import_klines_to_db(kline_data, db_path)
        print(f"✅ 数据已同步导入数据库: {db_path}")

    # 打印摘要
    print(f"\n{'='*50}")
    print(f"📊 数据摘要:")
    print(f"  币种数: {len(kline_data)}")
    print(f"  总 K 线数: {sum(len(df) for df in kline_data.values()):,}")
    print(f"  交易笔数: {len(trades_df)}")
    if not trades_df.empty:
        wins = trades_df['is_win'].sum()
        losses = trades_df['is_loss'].sum()
        print(f"  胜率: {wins}/{wins+losses} = {wins/(wins+losses)*100:.1f}%")
        print(f"  总盈亏: {trades_df['pnl'].sum():.2f} USDT")

    return kline_data, trades_df


if __name__ == "__main__":
    generate_sample_data()
