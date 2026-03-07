# -*- coding: UTF-8 -*-
"""
辅助函数模块

包含运动统计、计算等辅助函数
"""

import math


# 运动统计参数
CARBON_PER_STEP = 0.0014  # 公斤CO2/步
STEP_LENGTH_SLOW = 0.5    # 米
STEP_LENGTH_NORMAL = 0.65
STEP_LENGTH_FAST = 0.8


def calculate_pace(steps=None, duration_seconds=None):
    """
    计算配速
    返回: 配速 (分钟/公里)

    参数:
        steps: 步数
        duration_seconds: 持续时间（秒）

    返回:
        float: 配速（分钟/公里），None表示无法计算
    """
    if steps is None or duration_seconds is None:
        return None

    if steps <= 0 or duration_seconds <= 0:
        return None

    # 计算距离（米）
    distance_m = steps * STEP_LENGTH_NORMAL

    # 计算速度（米/秒）
    speed_mps = distance_m / duration_seconds

    if speed_mps <= 0:
        return None

    # 转换为配速（分钟/公里）
    # 速度 1 m/s = 3.6 km/h = 1000/60 = 16.667 m/min/km
    # 配速 = 1000 / (速度(m/s) * 60) = 1000 / (speed_mps * 60)
    pace = 1000 / (speed_mps * 60)

    return pace


def calculate_step_and_carbon(steps):
    """
    计算步数和碳排放

    参数:
        steps: 步数

    返回:
        dict: {"steps": 步数, "distance_km": 距离(公里), "carbon_kg": 碳排放(公斤)}
    """
    if steps <= 0:
        return {"steps": 0, "distance_km": 0, "carbon_kg": 0}

    # 计算距离（米）
    distance_m = steps * STEP_LENGTH_NORMAL
    distance_km = distance_m / 1000

    # 计算碳排放（公斤）
    carbon_kg = steps * CARBON_PER_STEP

    return {
        "steps": steps,
        "distance_km": round(distance_km, 2),
        "carbon_kg": round(carbon_kg, 4),
    }


def format_duration(seconds):
    """
    格式化时长

    参数:
        seconds: 秒数

    返回:
        str: 格式化后的字符串，如 "1小时23分45秒"
    """
    if seconds < 0:
        seconds = 0

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}小时{minutes}分{secs}秒"
    elif minutes > 0:
        return f"{minutes}分{secs}秒"
    else:
        return f"{secs}秒"


def format_pace(pace):
    """
    格式化配速

    参数:
        pace: 配速（分钟/公里）

    返回:
        str: 格式化后的字符串，如 "6'30\"/km"
    """
    if pace is None or pace <= 0 or pace > 60:
        return "--'--\""

    minutes = int(pace)
    seconds = int((pace - minutes) * 60)

    return f"{minutes}'{seconds:02d}\""
