# -*- coding: UTF-8 -*-
"""
日志模块

统一管理项目日志，支持：
- 控制台输出
- 文件输出（单次运行单文件）
- 可配置日志级别

使用方法:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("信息")
    logger.debug("调试信息")
"""

import logging
import os
import threading
from datetime import datetime


# 全局日志器缓存
_loggers = {}
_handler_lock = threading.Lock()
_session_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
_shared_file_handler = None
_shared_log_file = None


def _get_default_config():
    """获取默认日志配置。"""
    try:
        from config import LOG_CONFIG
        return LOG_CONFIG
    except ImportError:
        return {
            'log_level': 'INFO',
            'log_dir': 'logs',
            'log_to_file': True,
            'log_to_console': True,
            'log_file_prefix': 'run',
        }


def _ensure_log_dir(log_dir):
    """确保日志目录存在。"""
    os.makedirs(log_dir, exist_ok=True)


def _get_shared_file_handler(config, formatter, level):
    """获取本次运行共享的文件处理器。"""
    global _shared_file_handler, _shared_log_file

    if _shared_file_handler is not None:
        if level < _shared_file_handler.level:
            _shared_file_handler.setLevel(level)
        return _shared_file_handler

    with _handler_lock:
        if _shared_file_handler is not None:
            if level < _shared_file_handler.level:
                _shared_file_handler.setLevel(level)
            return _shared_file_handler

        log_dir = config.get('log_dir', 'logs')
        log_file_prefix = config.get('log_file_prefix', 'run')
        _ensure_log_dir(log_dir)

        _shared_log_file = os.path.join(log_dir, f'{log_file_prefix}_{_session_timestamp}.log')
        _shared_file_handler = logging.FileHandler(_shared_log_file, encoding='utf-8')
        _shared_file_handler.setLevel(level)
        _shared_file_handler.setFormatter(formatter)
        return _shared_file_handler


def get_log_file_path():
    """返回本次运行的日志文件路径。"""
    return _shared_log_file


def get_logger(name, config=None):
    """
    获取日志器

    参数:
        name: 日志器名称（通常使用 __name__）
        config: 配置字典，默认从 config 导入

    返回:
        logging.Logger: 日志器实例
    """
    if name in _loggers:
        return _loggers[name]

    if config is None:
        config = _get_default_config()

    level_str = config.get('log_level', 'INFO')
    level = getattr(logging, level_str.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        _loggers[name] = logger
        return logger

    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if config.get('log_to_console', True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if config.get('log_to_file', True):
        logger.addHandler(_get_shared_file_handler(config, formatter, level))

    _loggers[name] = logger
    return logger
