"""
OKX 交易助手 - 日志系统
"""
import logging
import os
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from trading.config import LOG_DIR, LOG_MAX_DAYS


def setup_logger(name: str = "trading", level=logging.INFO) -> logging.Logger:
    """配置日志：控制台 + 按天滚动文件"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s.%(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件（按天滚动，保留 90 天）
    log_file = LOG_DIR / f"{name}.log"
    fh = TimedRotatingFileHandler(
        str(log_file), when="midnight", interval=1, backupCount=LOG_MAX_DAYS, encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    fh.suffix = "%Y-%m-%d"
    logger.addHandler(fh)

    return logger


# 模块级 logger
log = setup_logger()
