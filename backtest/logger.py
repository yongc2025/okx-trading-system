"""
日志配置模块
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from backtest.config import LOG_DIR

def setup_logging(name: str = "backtest"):
    """配置全局日志"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件输出 (每个文件最大 10MB, 保留 5 个)
    log_file = LOG_DIR / f"{name}.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

# 创建全局主日志对象
logger = setup_logging()
