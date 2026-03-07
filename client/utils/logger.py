# -*- coding: UTF-8 -*-
"""
日志模块

统一管理项目日志，支持：
- 控制台输出
- 文件输出（带时间戳）
- 可配置日志级别

使用方法:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("信息")
    logger.debug("调试信息")
"""

import logging
import os
from datetime import datetime


# 全局日志器缓存
_loggers = {}


def get_logger(name, config=None):
    """
    获取日志器

    参数:
        name: 日志器名称（通常使用 __name__）
        config: 配置字典，默认从 config 导入

    返回:
        logging.Logger: 日志器实例
    """
    # 避免重复创建
    if name in _loggers:
        return _loggers[name]

    # 获取日志配置
    if config is None:
        try:
            from config import LOG_CONFIG
            config = LOG_CONFIG
        except ImportError:
            config = {
                'log_level': 'INFO',
                'log_dir': 'logs',
                'log_to_file': True,
                'log_to_console': True,
            }

    # 获取日志级别
    level_str = config.get('log_level', 'INFO')
    level = getattr(logging, level_str.upper(), logging.INFO)

    # 创建日志器
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        _loggers[name] = logger
        return logger

    # 日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 是否输出到控制台
    if config.get('log_to_console', True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 是否输出到文件
    if config.get('log_to_file', True):
        log_dir = config.get('log_dir', 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 带时间戳的日志文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'{name}_{timestamp}.log')

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 缓存日志器
    _loggers[name] = logger

    return logger
