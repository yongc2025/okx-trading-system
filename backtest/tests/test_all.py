"""
整合测试 (BT-11)
"""
import sys
from pathlib import Path

# 自动将项目根目录添加到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3
import pandas as pd
import numpy as np

from backtest.config import DB_PATH, DATA_DIR
from backtest.data.schema import init_database, reset_database, get_connection
from backtest.data.generate_sample import generate_sample_data
from backtest.data.database import get_trade_summary, get_symbol_list
from backtest.analysis.basic_stats import (
    calc_basic_stats, calc_consecutive_streaks, calc_equity_curve,
    calc_pnl_distribution, calc_monthly_stats, calc_symbol_stats, get_full_analysis,
)
from backtest.analysis.hold_loss import calc_holding_loss_analysis, get_holding_loss_analysis
from backtest.analysis.stoploss_sim import (
    simulate_stoploss_for_trade, simulate_stoploss_batch,
    calc_stoploss_comparison, get_stoploss_analysis,
)
from backtest.analysis.position_tier import analyze_position_tiers, get_position_tier_analysis
from backtest.analysis.extreme_scan import scan_single_symbol, get_scan_results, get_scan_summary

from backtest.logger import logger


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def check(self, name, condition, msg=""):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {name}")
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.errors.append(f"{name}: {msg}")
            logger.error(f"  ❌ {name} — {msg}")
            print(f"  ❌ {name} — {msg}")

    def summary(self):
        total = self.passed + self.failed
        logger.info(f"测试完毕: {self.passed}/{total} 通过, {self.failed} 失败")
        print(f"\n{'='*60}")
        print(f"测试结果: {self.passed}/{total} 通过, {self.failed} 失败")
        if self.errors:
            print(f"\n失败详情:")
            for e in self.errors:
                print(f"  - {e}")
        print(f"{'='*60}")
        return self.failed == 0


def test_schema():
    """测试数据库表结构"""
    logger.info("开始测试 1: 数据库表结构")
    print("\n📦 测试 1: 数据库表结构")
    t = TestResults()
    conn = init_database(":memory:")
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row['name'] for row in cur.fetchall()}
    t.check("trade_records 表存在", 'trade_records' in tables)
    t.check("position_snapshots 表存在", 'position_snapshots' in tables)
    t.check("scan_results 表存在", 'scan_results' in tables)
    t.check("app_settings 表存在", 'app_settings' in tables)
    t.check("import_status 表存在", 'import_status' in tables)
    conn.close()
    return t


def test_sample_data():
    """测试样本数据生成"""
    print("\n📦 测试 2: 样本数据生成")
    t = TestResults()
    conn = init_database(":memory:")
    conn.close()
    generate_sample_data(num_trades=100, db_path=str(DB_PATH) + ".test")

    conn = sqlite3.connect(str(DB_PATH) + ".test")
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT COUNT(*) as cnt FROM trade_records")
    cnt = cur.fetchone()['cnt']
    t.check("生成了交易记录", cnt > 0, f"记录数: {cnt}")
    t.check("记录数正确", cnt == 100, f"期望 100, 实际 {cnt}")

    cur = conn.execute("SELECT COUNT(*) as cnt FROM position_snapshots")
    snap_cnt = cur.fetchone()['cnt']
    t.check("生成了持仓快照", snap_cnt > 0, f"快照数: {snap_cnt}")

    conn.close()
    # 清理
    Path(str(DB_PATH) + ".test").unlink(missing_ok=True)
    return t


def test_basic_stats():
    """测试基础统计分析"""
    print("\n📦 测试 3: 基础统计分析")
    t = TestResults()

    # 构造测试数据
    df = pd.DataFrame({
        'pnl': [100, -50, 200, -30, 150, -80, 50, -20, 300, -100],
        'is_win': [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        'is_loss': [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        'entry_time': pd.date_range('2024-01-01', periods=10, freq='D').astype(str),
        'symbol': ['BTC'] * 10,
        'direction': ['long'] * 10,
        'trade_id': [f't{i}' for i in range(10)],
        'account_capital': [10000] * 10,
    })

    stats = calc_basic_stats(df)
    t.check("总交易笔数正确", stats['total_trades'] == 10, f"实际: {stats['total_trades']}")
    t.check("胜率正确", stats['wins'] == 5, f"实际: {stats['wins']}")
    t.check("胜率百分比存在", 'win_rate_pct' in stats)
    t.check("总盈亏正确", stats['total_pnl'] == 520, f"实际: {stats['total_pnl']}")
    t.check("盈亏比为正数", stats['profit_loss_ratio'] > 0)
    t.check("期望值存在", 'expectancy' in stats)

    # 连续统计
    streaks = calc_consecutive_streaks(df)
    t.check("最大连胜正确", streaks['max_consecutive_wins'] == 2, f"实际: {streaks['max_consecutive_wins']}")
    t.check("最大连亏正确", streaks['max_consecutive_losses'] == 1, f"实际: {streaks['max_consecutive_losses']}")

    # 净值曲线
    eq = calc_equity_curve(df)
    t.check("净值曲线非空", not eq.empty)
    t.check("净值曲线包含 equity 列", 'equity' in eq.columns)
    t.check("净值曲线包含 roi 列", 'roi' in eq.columns)
    t.check("净值曲线包含 drawdown 列", 'drawdown' in eq.columns)

    # 盈亏分布
    dist = calc_pnl_distribution(df)
    t.check("分布 bins 非空", len(dist['bins']) > 0)
    t.check("分布 counts 非空", len(dist['counts']) > 0)

    # 月度统计
    monthly = calc_monthly_stats(df)
    t.check("月度统计非空", not monthly.empty)

    # 币种统计
    sym = calc_symbol_stats(df)
    t.check("币种统计非空", not sym.empty)

    return t


def test_hold_loss():
    """测试扛单分析"""
    print("\n📦 测试 4: 扛单行为分析")
    t = TestResults()

    df = pd.DataFrame({
        'pnl': [-100, -200, 50, -150, 80],
        'is_win': [0, 0, 1, 0, 1],
        'is_loss': [1, 1, 0, 1, 0],
        'entry_time': pd.date_range('2024-01-01', periods=5, freq='D').astype(str),
        'symbol': ['BTC'] * 5,
        'direction': ['long'] * 5,
        'trade_id': [f't{i}' for i in range(5)],
        'max_floating_loss': [-150, -300, -20, -250, -10],
        'max_floating_loss_rate': [0.15, 0.30, 0.02, 0.25, 0.01],
        'exceeded_stoploss': [1, 1, 0, 1, 0],
        'pnl_rate': [-0.10, -0.20, 0.05, -0.15, 0.08],
        'leverage': [2, 3, 1, 2, 1],
        'account_capital': [10000] * 5,
    })

    result = calc_holding_loss_analysis(df)
    t.check("总亏损笔数正确", result['total_loss_trades'] == 3)
    t.check("超止损线笔数正确", result['exceeded_stoploss_count'] == 3)
    t.check("严重程度分布存在", 'severity_distribution' in result)
    t.check("散点图数据存在", 'scatter_data' in result)
    t.check("币种统计存在", 'symbol_holding_stats' in result)
    t.check("对比数据存在", 'comparison' in result)
    t.check("扛单笔数正确", result['comparison']['holding']['count'] == 3)

    return t


def test_stoploss():
    """测试止损回测"""
    print("\n📦 测试 5: 止损回测模拟")
    t = TestResults()

    df = pd.DataFrame({
        'pnl': [100, -500, 200, -300, 150],
        'is_win': [1, 0, 1, 0, 1],
        'is_loss': [0, 1, 0, 1, 0],
        'entry_time': pd.date_range('2024-01-01', periods=5, freq='D').astype(str),
        'symbol': ['BTC'] * 5,
        'direction': ['long'] * 5,
        'trade_id': [f't{i}' for i in range(5)],
        'entry_cost': [1000] * 5,
        'leverage': [2] * 5,
        'account_capital': [10000] * 5,
    })

    # 单笔模拟
    sim = simulate_stoploss_for_trade(df.iloc[1], 0.10)
    t.check("止损模拟触发", sim['simulated'] == True)
    t.check("止损后亏损减少", sim['pnl_diff'] > 0)

    # 批量模拟
    batch = simulate_stoploss_batch(df, 0.10)
    t.check("批量模拟非空", not batch.empty)
    t.check("simulated 列存在", 'simulated' in batch.columns)

    # 多比例对比
    comp = calc_stoploss_comparison(df)
    t.check("对比表存在", 'comparison_table' in comp)
    t.check("对比表包含5行", len(comp['comparison_table']) == 5)
    t.check("止损比例列表存在", 'stoploss_ratios' in comp)

    return t


def test_position_tier():
    """测试仓位分层分析"""
    print("\n📦 测试 6: 仓位策略分层分析")
    t = TestResults()

    df = pd.DataFrame({
        'pnl': [100, -50, 200, -30, 150, -80, 50, -20],
        'is_win': [1, 0, 1, 0, 1, 0, 1, 0],
        'is_loss': [0, 1, 0, 1, 0, 1, 0, 1],
        'entry_time': pd.date_range('2024-01-01', periods=8, freq='D').astype(str),
        'symbol': ['BTC'] * 4 + ['ETH'] * 4,
        'direction': ['long'] * 8,
        'trade_id': [f't{i}' for i in range(8)],
        'position_tier': ['first', 'first', 'add1', 'add1', 'first', 'add1', 'add2', 'add2'],
        'exceeded_stoploss': [0, 0, 0, 1, 0, 1, 0, 0],
        'max_floating_loss_rate': [0.05, 0.08, 0.03, 0.15, 0.04, 0.12, 0.06, 0.09],
        'account_capital': [10000] * 8,
    })

    result = analyze_position_tiers(df)
    t.check("首仓统计存在", 'first_position' in result)
    t.check("加仓1统计存在", 'add1' in result)
    t.check("加仓2统计存在", 'add2' in result)
    t.check("加仓后整体存在", 'after_add' in result)
    t.check("全部交易存在", 'total' in result)
    t.check("档位分布存在", 'tier_distribution' in result)
    t.check("完成度分布存在", 'completion_distribution' in result)
    t.check("对比数据存在", 'comparison' in result)
    t.check("首仓笔数正确", result['first_position']['total_trades'] == 3)
    t.check("加仓1笔数正确", result['add1']['total_trades'] == 3)

    return t


def test_extreme_scan():
    """测试极端行情扫描"""
    print("\n📦 测试 7: 极端行情扫描引擎")
    t = TestResults()

    # 构造测试 K 线数据
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=10, freq='1min'),
        'open': [100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
        'high': [105, 103, 130, 95, 102, 101, 150, 80, 103, 101],
        'low': [95, 97, 95, 70, 98, 99, 95, 70, 97, 99],
        'close': [103, 98, 125, 75, 101, 100, 140, 85, 102, 100],
        'volume': [1000] * 10,
    })

    results = scan_single_symbol("TEST", df, threshold=0.10)
    t.check("发现了极端事件", len(results) > 0, f"发现 {len(results)} 个")

    for r in results:
        t.check(f"事件包含必要字段", all(k in r for k in ['symbol', 'scan_time', 'direction', 'change_pct']))
        t.check(f"涨跌幅超过阈值", abs(r['change_pct']) >= 0.10, f"实际: {r['change_pct']}")
        t.check(f"方向正确", r['direction'] in ['surge', 'plunge'])

    # 空数据测试
    empty_results = scan_single_symbol("EMPTY", pd.DataFrame(), threshold=0.10)
    t.check("空数据返回空列表", len(empty_results) == 0)

    return t


def test_api_integration():
    """测试 API 集成"""
    print("\n📦 测试 8: API 集成")
    t = TestResults()

    # 生成测试数据
    test_db = str(DB_PATH) + ".api_test"
    generate_sample_data(num_trades=50, db_path=test_db)

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row

    # 测试 summary
    summary = get_trade_summary(conn)
    t.check("summary 包含 total", 'total' in summary)
    t.check("summary 包含 wins", 'wins' in summary)
    t.check("summary 包含 total_pnl", 'total_pnl' in summary)

    # 测试 symbol list
    symbols = get_symbol_list(conn)
    t.check("币种列表非空", len(symbols) > 0)

    conn.close()
    Path(test_db).unlink(missing_ok=True)
    return t


def test_edge_cases():
    """测试边界情况"""
    print("\n📦 测试 9: 边界情况")
    t = TestResults()

    # 空 DataFrame
    empty_df = pd.DataFrame()
    t.check("空DF基础统计返回错误", 'error' in calc_basic_stats(empty_df))
    t.check("空DF扛单分析返回错误", 'error' in calc_holding_loss_analysis(empty_df))

    # 无平仓交易
    open_only = pd.DataFrame({'pnl': [None, None], 'is_win': [None, None], 'is_loss': [None, None]})
    t.check("无平仓交易基础统计返回错误", 'error' in calc_basic_stats(open_only))

    # 全盈利交易
    all_win = pd.DataFrame({
        'pnl': [100, 200, 50],
        'is_win': [1, 1, 1],
        'is_loss': [0, 0, 0],
        'entry_time': pd.date_range('2024-01-01', periods=3).astype(str),
        'symbol': ['BTC'] * 3,
        'direction': ['long'] * 3,
        'trade_id': ['t0', 't1', 't2'],
        'account_capital': [10000] * 3,
    })
    stats = calc_basic_stats(all_win)
    t.check("全盈利胜率100%", stats['win_rate'] == 1.0)

    return t


def main():
    logger.info("开始执行整合测试...")
    print("🧪 OKX 量化回测 system - 整合测试")
    print("=" * 60)

    all_results = [
        test_schema(),
        test_sample_data(),
        test_basic_stats(),
        test_hold_loss(),
        test_stoploss(),
        test_position_tier(),
        test_extreme_scan(),
        test_api_integration(),
        test_edge_cases(),
    ]

    total_passed = sum(r.passed for r in all_results)
    total_failed = sum(r.failed for r in all_results)
    total = total_passed + total_failed

    logger.info(f"所有测试执行完毕。总通过: {total_passed}, 总失败: {total_failed}")

    print(f"\n{'='*60}")
    print(f"📊 总测试结果: {total_passed}/{total} 通过, {total_failed} 失败")

    if total_failed > 0:
        print(f"\n❌ 失败详情:")
        for r in all_results:
            for e in r.errors:
                print(f"  - {e}")
        logger.error("测试未通过，存在失败项")
        sys.exit(1)
    else:
        logger.info("恭喜！所有测试通过。")
        print(f"\n✅ 全部测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()
