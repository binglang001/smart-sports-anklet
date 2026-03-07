# -*- coding: UTF-8 -*-
"""
调试日志模块

记录步数、姿态、跌倒检测的详细数据用于分析
使用批量写入优化性能，避免阻塞采样线程
"""

import os
import sys
import time
import threading
import queue
from datetime import datetime

# 导入日志模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
logger = get_logger('utils.debug')


class DebugLogger:
    """调试数据记录器 - 支持批量写入"""

    def __init__(self, debug_dir=None, enabled=False, batch_size=10, flush_interval=1.0):
        self.enabled = enabled
        self.debug_dir = debug_dir or "debug_data"
        self.batch_size = batch_size  # 批量写入大小
        self.flush_interval = flush_interval  # 强制刷新间隔(秒)

        self.file_handle = None
        self._buffer = []  # 内存缓冲
        self._buffer_lock = threading.Lock()
        self._last_flush = time.time()

        # 后台写入线程
        self._write_thread = None
        self._running = False
        self._queue = queue.Queue(maxsize=1000)  # 异步队列

    def start(self):
        """启动日志记录"""
        logger.debug(f"DebugLogger.start() called, enabled={self.enabled}")
        if not self.enabled:
            return

        os.makedirs(self.debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.debug_dir, f"debug_{timestamp}.csv")
        self.file_handle = open(filepath, 'w', encoding='utf-8')
        self.file_handle.write(
            "timestamp,type,acc_x,acc_y,acc_z,acc_magnitude,pitch,roll,"
            "step_detected,threshold,mean_acc,std_acc,posture,motion_level,"
            "fall_state,variance,peak_acc,min_acc,angle_change\n"
        )
        self.file_handle.flush()
        logger.info(f"CSV文件已创建: {filepath}")

    def stop(self):
        """停止日志记录"""
        if self._running:
            self._running = False
            if self._write_thread:
                self._write_thread.join(timeout=2.0)

        # 最后一次刷新缓冲
        self._flush_buffer()

        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

    def _flush_buffer(self):
        """刷新缓冲区到文件"""
        if not self._buffer or not self.file_handle:
            return

        with self._buffer_lock:
            if not self._buffer:
                return

            # 写入所有缓冲行
            for line in self._buffer:
                self.file_handle.write(line)
            self.file_handle.flush()
            self._buffer.clear()
            self._last_flush = time.time()

    def _write_line(self, line):
        """写入一行数据（带缓冲）"""
        if not self.enabled:
            return
        if not self.file_handle:
            return

        with self._buffer_lock:
            self._buffer.append(line)

            # 达到批量大小或超时则刷新
            if len(self._buffer) >= self.batch_size or \
               (time.time() - self._last_flush) >= self.flush_interval:
                for l in self._buffer:
                    self.file_handle.write(l)
                self.file_handle.flush()
                self._buffer.clear()
                self._last_flush = time.time()

    def log_step(self, acc_x, acc_y, acc_z, acc_mag, threshold_upper, threshold_lower, mean_acc, std_acc, detected):
        """记录步数检测数据"""
        if not self.enabled:
            return
        if not self.file_handle:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # CSV格式: timestamp,type,acc_x,acc_y,acc_z,acc_magnitude,pitch,roll,step_detected,threshold_upper,threshold_lower,mean_acc,std_acc,posture,motion_level,fall_state,variance,peak_acc,min_acc,angle_change
        # 步数记录: pitch=0, roll=0, posture="none", motion_level=0, fall_state="none", variance=0, peak_acc=0, min_acc=0, angle_change=0
        line = (
            f"{timestamp},step,{acc_x:.4f},{acc_y:.4f},{acc_z:.4f},"
            f"{acc_mag:.4f},0.00,0.00,{detected},{threshold_upper:.4f},{threshold_lower:.4f},"
            f"{mean_acc:.4f},{std_acc:.4f},none,0.0000,none,0.0000,0.0000,0.0000,0.0000\n"
        )
        self._write_line(line)

    def log_posture(self, acc_x, acc_y, acc_z, acc_mag, pitch, roll, posture, motion_level):
        """记录姿态检测数据"""
        if not self.enabled:
            return
        if not self.file_handle:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # CSV格式: timestamp,type,acc_x,acc_y,acc_z,acc_magnitude,pitch,roll,step_detected,threshold,mean_acc,std_acc,posture,motion_level,fall_state,variance,peak_acc,min_acc,angle_change
        # 姿态记录: step_detected=False, threshold=0, mean_acc=0, std_acc=0, fall_state="none", variance=0, peak_acc=0, min_acc=0, angle_change=0
        line = (
            f"{timestamp},posture,{acc_x:.4f},{acc_y:.4f},{acc_z:.4f},"
            f"{acc_mag:.4f},{pitch:.2f},{roll:.2f},False,0.0000,0.0000,0.0000,"
            f"{posture},{motion_level:.4f},none,0.0000,0.0000,0.0000,0.0000\n"
        )
        self._write_line(line)

    def log_fall(self, acc_x, acc_y, acc_z, total_acc, pitch, roll,
                 state, variance, peak_acc, min_acc, angle_change):
        """记录跌倒检测数据"""
        if not self.enabled:
            return
        if not self.file_handle:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # CSV格式: timestamp,type,acc_x,acc_y,acc_z,acc_magnitude,pitch,roll,step_detected,threshold,mean_acc,std_acc,posture,motion_level,fall_state,variance,peak_acc,min_acc,angle_change
        # 跌倒记录: step_detected=False, threshold=0, mean_acc=0, std_acc=0, posture="none", motion_level=0
        line = (
            f"{timestamp},fall,{acc_x:.4f},{acc_y:.4f},{acc_z:.4f},"
            f"{total_acc:.4f},{pitch:.2f},{roll:.2f},False,0.0000,0.0000,0.0000,"
            f"none,0.0000,{state},{variance:.4f},{peak_acc:.4f},{min_acc:.4f},"
            f"{angle_change:.2f}\n"
        )
        self._write_line(line)

    def flush(self):
        """手动刷新缓冲区"""
        self._flush_buffer()


def init_debug(enabled=True, debug_dir="debug_data", batch_size=10, flush_interval=1.0):
    """初始化调试日志器"""
    logger = DebugLogger(
        debug_dir=debug_dir,
        enabled=enabled,
        batch_size=batch_size,
        flush_interval=flush_interval
    )
    logger.start()
    return logger
