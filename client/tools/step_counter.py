# -*- coding: UTF-8 -*-
"""
步数计算程序

使用主程序的StepDetector模块进行步数检测
输入：采集的数据文件（包含预处理后的线性加速度）
输出：检测到的步数和统计信息
"""

import csv
import os
import sys
import math
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入日志模块
from utils.logger import get_logger
logger = get_logger('tools.step_counter')


def load_data(csv_file):
    """加载CSV数据"""
    data = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({
                'timestamp': float(row['timestamp']),
                'sample_idx': int(row['sample_idx']),
                # 原始加速度
                'acc_x': float(row['acc_x']),
                'acc_y': float(row['acc_y']),
                'acc_z': float(row['acc_z']),
                'acc_magnitude': float(row['acc_magnitude']),
                # 预处理后的线性加速度
                'linear_x': float(row['linear_x']),
                'linear_y': float(row['linear_y']),
                'linear_z': float(row['linear_z']),
            })
    return data


def run_step_detection(csv_file, t_max=1.5, t_min=-0.5):
    """
    运行步数检测

    参数:
        csv_file: CSV数据文件路径
        t_max: 波峰阈值 (g)
        t_min: 波谷阈值 (g)
    """
    # 加载数据
    data = load_data(csv_file)
    if not data:
        logger.error(f"无法加载数据: {csv_file}")
        return

    logger.info("=" * 50)
    logger.info("步数检测 - 使用主程序模块")
    logger.info("=" * 50)
    logger.info(f"数据文件: {csv_file}")
    logger.info(f"数据点数: {len(data)}")

    # 计算采样率
    if len(data) > 1:
        duration = data[-1]['timestamp'] - data[0]['timestamp']
        sample_rate = len(data) / duration if duration > 0 else 0
        logger.info(f"采样率: {sample_rate:.1f} Hz")
        logger.info(f"时长: {duration:.1f} 秒")

    # 使用主程序的StepDetector
    from sensors.step_detector import StepDetector

    config = {
        "t_max": t_max,
        "t_min": t_min,
        "window_size": 7,
        "min_interval_ms": 250,
        "max_interval_ms": 2000,
    }
    detector = StepDetector(config)

    # 逐样本添加进行步数检测
    steps_detected = []
    for i, sample in enumerate(data):
        linear_x = sample['linear_x']
        linear_y = sample['linear_y']
        linear_z = sample['linear_z']
        timestamp = sample['timestamp']

        # 使用线性加速度的合量进行检测
        step_detected, _ = detector.add_sample(
            linear_x, linear_y, linear_z,
            timestamp=timestamp
        )

        if step_detected:
            steps_detected.append(timestamp)

    # 输出结果
    step_count = detector.get_step_count()
    logger.info(f"[检测结果]")
    logger.info(f"检测到的步数: {step_count}")

    if len(steps_detected) > 1:
        intervals = [steps_detected[i+1] - steps_detected[i]
                    for i in range(len(steps_detected)-1)]
        avg_interval = sum(intervals) / len(intervals)
        avg_step_freq = 1.0 / avg_interval if avg_interval > 0 else 0
        logger.info(f"平均步频: {avg_step_freq:.1f} 步/分钟")
        logger.info(f"平均步间隔: {avg_interval*1000:.0f} ms")

    return step_count


def main():
    parser = argparse.ArgumentParser(description='步数检测 - 使用主程序模块')
    parser.add_argument('file', help='CSV数据文件路径')
    parser.add_argument('--t-max', type=float, default=1.5, help='波峰阈值 (默认1.5g)')
    parser.add_argument('--t-min', type=float, default=-0.5, help='波谷阈值 (默认-0.5g)')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"文件不存在: {args.file}")
        return

    run_step_detection(args.file, args.t_max, args.t_min)


if __name__ == '__main__':
    main()
