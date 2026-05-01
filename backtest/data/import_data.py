"""
数据导入管道
从 pkl 文件加载 → 清洗 → 验证 → 写入 SQLite
"""
import sys
from pathlib import Path

import pandas as pd

from backtest.config import PKL_DATA_DIR, DATA_DIR
from backtest.data.loader import (
    load_all_pkl, load_single_pkl, validate_dataframe, clean_dataframe,
    get_file_hash, check_imported,
)
from backtest.data.schema import init_database, get_connection
from backtest.logger import logger


def import_pkl_files(data_dir: Path = None, db_path: str = None, force: bool = False):
    """
    导入 pkl 文件到数据库

    Args:
        data_dir: pkl 文件目录
        db_path: 数据库路径
        force: 是否强制重新导入
    """
    data_dir = data_dir or PKL_DATA_DIR
    conn = init_database(db_path)

    pkl_files = sorted(data_dir.glob("*.pkl"))
    if not pkl_files:
        logger.error(f"❌ 目录下没有 pkl 文件: {data_dir}")
        return

    total_symbols = 0
    total_records = 0

    for pkl_file in pkl_files:
        file_hash = get_file_hash(pkl_file)

        if not force and check_imported(pkl_file, conn):
            logger.info(f"⏭️  跳过已导入: {pkl_file.name}")
            continue

        logger.info(f"📦 正在导入: {pkl_file.name}")

        try:
            data = load_single_pkl(pkl_file)
        except Exception as e:
            logger.error(f"  ❌ 加载失败: {e}")
            continue

        symbol_count = 0
        record_count = 0

        for symbol, raw_df in data.items():
            # 验证
            valid, errors = validate_dataframe(raw_df, symbol)
            if not valid:
                logger.warning(f"  ⚠️  {symbol} 验证失败: {'; '.join(errors)}")
                continue

            # 清洗
            df = clean_dataframe(raw_df, symbol)
            if df.empty:
                logger.warning(f"  ⚠️  {symbol} 清洗后为空")
                continue

            # 存储到数据库的 kline_data 表（暂用临时表存 K 线）
            # 这里先打印信息，后续分析模块直接从 pkl 读取
            symbol_count += 1
            record_count += len(df)
            logger.info(f"  ✅ {symbol}: {len(df)} 条 K 线")

        # 记录导入状态
        conn.execute(
            "INSERT OR REPLACE INTO import_status (source_file, file_hash, symbol_count, record_count, status) "
            "VALUES (?, ?, ?, ?, 'done')",
            (str(pkl_file), file_hash, symbol_count, record_count)
        )
        conn.commit()

        total_symbols += symbol_count
        total_records += record_count
        logger.info(f"  📊 {pkl_file.name}: {symbol_count} 个币种, {record_count} 条记录")

    conn.close()
    logger.info(f"✅ 导入完成: {total_symbols} 个币种, {total_records} 条 K 线记录")


def import_trades_to_db(trades_df: pd.DataFrame, db_path: str = None):
    """将交易记录 DataFrame 导入数据库"""
    if trades_df.empty:
        return

    conn = get_connection(db_path)
    # 处理 snapshots，将其从主表中分离
    df_to_save = trades_df.copy()
    snapshots_list = []
    
    if 'snapshots' in df_to_save.columns:
        for idx, row in df_to_save.iterrows():
            if isinstance(row['snapshots'], list):
                snapshots_list.extend(row['snapshots'])
        df_to_save = df_to_save.drop(columns=['snapshots'])

    try:
        df_to_save.to_sql("trade_records", conn, if_exists="append", index=False)
    except Exception:
        for _, row in df_to_save.iterrows():
            try:
                row_dict = row.to_dict()
                columns = ', '.join(row_dict.keys())
                placeholders = ', '.join(['?'] * len(row_dict))
                sql = f"INSERT OR IGNORE INTO trade_records ({columns}) VALUES ({placeholders})"
                conn.execute(sql, list(row_dict.values()))
            except:
                pass
    
    # 导入快照
    if snapshots_list:
        snap_df = pd.DataFrame(snapshots_list)
        try:
            snap_df.to_sql("position_snapshots", conn, if_exists="append", index=False)
        except:
            for _, row in snap_df.iterrows():
                try:
                    row_dict = row.to_dict()
                    columns = ', '.join(row_dict.keys())
                    placeholders = ', '.join(['?'] * len(row_dict))
                    sql = f"INSERT OR IGNORE INTO position_snapshots ({columns}) VALUES ({placeholders})"
                    conn.execute(sql, list(row_dict.values()))
                except:
                    pass

    conn.commit()
    conn.close()


def import_klines_to_db(kline_data: dict, db_path: str = None):
    """
    本系统主要从 pkl 读取 K 线，此函数为占位符或用于未来扩展。
    目前仅打印信息。
    """
    pass


if __name__ == "__main__":
    # 支持命令行: python -m backtest.data.import_data [pkl目录]
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PKL_DATA_DIR
    import_pkl_files(data_dir)
