# -*- coding: UTF-8 -*-
"""
高频采样模块

50Hz采样 + 重力去除
- 采样率: 50Hz
- 处理: 实时重力去除 + 滑动平均滤波

论文算法:
1. 《基于MEMS六轴传感器的上肢运动识别系统》(胡成全等)
"""

import time
import threading
import math
import os
import sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入config获取debug设置
import config
from utils.logger import get_logger

# 获取日志器
logger = get_logger('sensors.high_freq_sampler')

# Debug开关
DEBUG_SAMPLER = config.DEBUG_ENABLED


# 默认配置
SAMPLE_RATE_HZ = 50  # 采样率50Hz
SAMPLE_INTERVAL = 1.0 / SAMPLE_RATE_HZ


class HighFrequencySampler:
    """高频采样器 - 50Hz采样 + 重力去除

    架构:
    - 采样线程: 50Hz定时采样
    - 处理: 单线程实时重力去除
    """

    def __init__(self, sample_rate=SAMPLE_RATE_HZ):
        self.sample_rate = sample_rate
        self.sample_interval = 1.0 / sample_rate

        # 线程控制
        self._running = False
        self._sample_thread = None

        # 采样缓冲
        self._sample_buffer = deque(maxlen=sample_rate * 10)  # 10秒数据

        # 最新值
        self._latest_raw = (0.0, 0.0, 0.0, 0.0)
        self._latest_linear = (0.0, 0.0, 0.0, 0.0)
        self._lock = threading.Lock()

        # 采样统计
        self._sample_count = 0
        self._start_time = 0

        # 重力去除器
        self._gravity_remover = None

    def start(self):
        """启动采样"""
        if self._running:
            return True

        self._running = True
        self._sample_count = 0

        # 导入传感器读取函数
        try:
            from sensors.icm20689 import read_acc_gyro
            self._read_func = read_acc_gyro
        except Exception as e:
            logger.critical(f"无法导入ICM20689模块: {e}")
            self._running = False
            raise RuntimeError(f"传感器初始化失败: {e}")

        # 测试传感器读取
        try:
            test_data = self._read_func()
            if test_data is None or test_data[0] is None:
                raise RuntimeError("传感器读取返回空数据")
        except Exception as e:
            logger.critical(f"传感器测试读取失败: {e}")
            self._running = False
            raise RuntimeError(f"传感器测试失败: {e}")

        # 初始化重力去除器
        from sensors.gravity_remover import GravityRemover
        # 从config读取参数
        gravity_config = config.GRAVITY_REMOVER_CONFIG
        self._gravity_remover = GravityRemover(gravity_config)

        # 开启重力去除器debug
        import sensors.gravity_remover as gr_module
        gr_module.DEBUG_GRAVITY = config.DEBUG_ENABLED
        logger.info(f"重力去除器已初始化, filter_alpha={gravity_config['filter_alpha']}, filter_window={gravity_config['filter_window']}")

        # 启动采样线程
        self._sample_thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="HF-Sampler"
        )
        self._sample_thread.start()

        logger.info(f"已启动 ({self.sample_rate}Hz采样)")
        return True

    def stop(self):
        """停止采样"""
        self._running = False
        if self._sample_thread:
            self._sample_thread.join(timeout=2.0)

        stats = self.get_stats()
        logger.info(f"已停止，采样 {self._sample_count} 次")

    def _sample_loop(self):
        """采样循环"""
        self._start_time = time.perf_counter()
        logger.info(f"采样线程启动, rate={self.sample_rate}Hz, 间隔={self.sample_interval*1000:.2f}ms")

        sample_idx = 0
        error_count = 0
        last_sample_time = 0.0

        while self._running:
            loop_start = time.perf_counter()

            # 计算下一次采样时间
            next_sample_time = loop_start + self.sample_interval

            # 采样一次
            try:
                ax, ay, az, gx, gy, gz = self._read_func()

                if ax is None:
                    error_count += 1
                    if error_count > 5:
                        logger.critical(f"传感器读取失败次数过多({error_count}次)，停止采样")
                        self._running = False
                        break
                else:
                    error_count = 0
            except Exception as e:
                logger.critical(f"传感器读取异常: {e}")
                self._running = False
                raise

            if ax is not None:
                # 时间戳
                timestamp = time.perf_counter()
                acc_mag = math.sqrt(ax**2 + ay**2 + az**2)

                # 实时重力去除
                if self._gravity_remover:
                    linear_x, linear_y, linear_z = self._gravity_remover.add_sample(
                        ax, ay, az, gx, gy, gz, timestamp
                    )
                    gravity_x, gravity_y, gravity_z = self._gravity_remover.get_gravity()
                else:
                    linear_x, linear_y, linear_z = ax, ay, az
                    gravity_x, gravity_y, gravity_z = 0.0, 0.0, 0.0

                linear_mag = math.sqrt(linear_x**2 + linear_y**2 + linear_z**2)

                if DEBUG_SAMPLER and sample_idx % 50 == 0:
                    logger.debug(f"[采样] idx={sample_idx}, 原始=({ax:.4f}, {ay:.4f}, {az:.4f}), 线性=({linear_x:.4f}, {linear_y:.4f}, {linear_z:.4f})")

                with self._lock:
                    self._sample_buffer.append({
                        'sample_idx': sample_idx,
                        'timestamp': timestamp,
                        'ax': ax, 'ay': ay, 'az': az,
                        'gx': gx if gx else 0,
                        'gy': gy if gy else 0,
                        'gz': gz if gz else 0,
                        'gravity_x': gravity_x,
                        'gravity_y': gravity_y,
                        'gravity_z': gravity_z,
                        'linear_x': linear_x,
                        'linear_y': linear_y,
                        'linear_z': linear_z,
                        'linear_mag': linear_mag,
                        'acc_mag': acc_mag
                    })
                    self._latest_raw = (ax, ay, az, acc_mag)
                    self._latest_linear = (linear_x, linear_y, linear_z, linear_mag)
                    self._sample_count += 1
                    sample_idx += 1
                    last_sample_time = timestamp

            # 睡眠等待到下一次采样
            sleep_time = next_sample_time - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_latest_raw(self):
        """获取最新原始加速度"""
        with self._lock:
            return self._latest_raw

    def get_latest_linear(self):
        """获取最新线性加速度"""
        with self._lock:
            return self._latest_linear

    def get_output_buffer(self):
        """获取采样缓冲区数据"""
        with self._lock:
            return list(self._sample_buffer)

    def clear_buffer(self):
        """清空输出缓冲区"""
        with self._lock:
            self._sample_buffer.clear()

    def get_stats(self):
        """获取采样统计"""
        elapsed = time.perf_counter() - self._start_time
        actual_rate = self._sample_count / elapsed if elapsed > 0 else 0
        return {
            'sample_count': self._sample_count,
            'sample_rate': self.sample_rate,
            'actual_sample_rate': actual_rate,
            'elapsed': elapsed
        }


# 全局单例
_sampler_instance = None


def get_sampler():
    """获取全局采样器实例"""
    global _sampler_instance
    if _sampler_instance is None:
        _sampler_instance = HighFrequencySampler()
    return _sampler_instance


def start_sampling():
    """启动采样"""
    sampler = get_sampler()
    return sampler.start()


def stop_sampling():
    """停止采样"""
    global _sampler_instance
    if _sampler_instance:
        _sampler_instance.stop()
        _sampler_instance = None


def get_latest_acceleration():
    """获取最新加速度值"""
    sampler = get_sampler()
    ax, ay, az, mag = sampler.get_latest_linear()
    return ax, ay, az, mag


def get_sample_buffer():
    """获取采样缓冲区"""
    sampler = get_sampler()
    return sampler.get_output_buffer()


def get_sampling_stats():
    """获取采样统计"""
    sampler = get_sampler()
    return sampler.get_stats()
