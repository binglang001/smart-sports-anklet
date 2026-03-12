# -*- coding: UTF-8 -*-
"""tools 目录共享辅助函数。"""

import os
import sys


TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(TOOLS_DIR)


def ensure_project_root():
    """确保 client 根目录在导入路径中。"""
    if CLIENT_DIR not in sys.path:
        sys.path.insert(0, CLIENT_DIR)
    return CLIENT_DIR


def get_client_data_dir(*parts):
    """获取 client/data 下的目录或文件路径。"""
    return os.path.join(CLIENT_DIR, "data", *parts)


def ensure_output_dir(path):
    """确保输出目录存在。"""
    os.makedirs(path, exist_ok=True)
    return path


def build_timestamped_filename(output_dir, prefix, suffix=".csv"):
    """生成带时间戳的输出文件名。"""
    import time

    ensure_output_dir(output_dir)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(output_dir, f"{prefix}_{timestamp}{suffix}")


def setup_chinese_font():
    """配置 matplotlib 中文字体。"""
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    return plt
