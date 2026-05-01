"""
OKX 量化回测系统 - 一键启动
"""
import sys
from pathlib import Path

# 自动将项目根目录添加到 sys.path
# PROJECT_ROOT 指向 okx-trading-system (backtest 的上一级)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.config import WEB_HOST, WEB_PORT
from backtest.data.schema import init_database
from backtest.logger import logger


def main():
    logger.info("🚀 OKX 量化回测系统启动")

    # 初始化数据库
    logger.info("📦 初始化数据库...")
    init_database()

    # 检查数据
    from backtest.config import DB_PATH
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT COUNT(*) FROM trade_records")
    count = cur.fetchone()[0]
    conn.close()

    if count == 0:
        logger.warning("⚠️  数据库为空，正在生成样本数据...")
        from backtest.data.generate_sample import generate_sample_data
        generate_sample_data(num_trades=500)
    else:
        logger.info(f"✅ 数据库已有 {count} 条交易记录")

    # 启动 Web 服务
    logger.info(f"🌐 启动 Web 服务: http://{WEB_HOST}:{WEB_PORT}")
    print(f"   本地访问: http://localhost:{WEB_PORT}")
    print("=" * 40)

    import uvicorn
    # 修改导入路径，避免 uvicorn 因 CWD 不同导致找不到 backtest.app
    uvicorn.run("backtest.api.app:app", host=WEB_HOST, port=WEB_PORT, reload=True)


if __name__ == "__main__":
    main()
