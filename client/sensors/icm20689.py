# -*- coding: UTF-8 -*-
"""
ICM20689 加速度传感器直接读取模块

使用/dev/icm20689设备直接读取加速度数据
实现50Hz高频采样

设备信息:
  - 路径: /dev/icm20689
  - 权限: 600 (root专属)
  - 数据格式: 6字节, 小端序, 3×int16 (X, Y, Z)
  - 灵敏度: 16384 LSB/g (±2g范围）
"""

import os
import struct
import time
import math

# 导入日志模块
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
logger = get_logger('sensors.icm20689')

# 设备路径
DEVICE_PATH = "/dev/icm20689"

# ICM20689参数
ACC_SCALE = 2048.0   # ±16g范围的灵敏度
GYRO_SCALE = 131.0   # ±250°/s范围的灵敏度


class ICM20689:
    """ICM20689加速度传感器直接读取"""

    def __init__(self, device_path=DEVICE_PATH):
        self.device_path = device_path
        self.fd = None
        self.is_opened = False

    def open(self):
        """打开设备"""
        if self.is_opened:
            return True

        try:
            self.fd = os.open(self.device_path, os.O_RDONLY)
            self.is_opened = True
            return True
        except (OSError, PermissionError) as e:
            logger.error(f"打开设备失败: {e}")
            return False

    def close(self):
        """关闭设备"""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception as e:
                logger.warning(f"关闭设备时出错: {e}")
        self.fd = None
        self.is_opened = False

    def read_raw(self):
        """
        读取原始加速度数据
        返回: (x, y, z) - int16原始值
        """
        if not self.is_opened:
            return None, None, None

        try:
            data = os.read(self.fd, 6)
            x, y, z = struct.unpack('<hhh', data)
            return x, y, z
        except Exception as e:
            logger.error(f"读取失败: {e}")
            return None, None, None

    def read_g(self):
        """
        读取加速度并转换为g值
        返回: (x_g, y_g, z_g) - float g值
        """
        x, y, z = self.read_raw()
        if x is None:
            return None, None, None

        return x / ACC_SCALE, y / ACC_SCALE, z / ACC_SCALE

    def read_magnitude(self):
        """
        读取加速度幅值
        返回: float - 加速度合量 (g)
        """
        x, y, z = self.read_g()
        if x is None:
            return None

        return math.sqrt(x**2 + y**2 + z**2)

    def read_gyro(self):
        """
        读取陀螺仪数据
        返回: (x_dps, y_dps, z_dps) - °/s
        """
        if not self.is_opened:
            return None, None, None

        try:
            data = os.read(self.fd, 14)
            if len(data) < 14:
                return None, None, None

            # 跳过加速度6字节，读取陀螺仪6字节
            gyro_x = struct.unpack('<h', data[8:10])[0]
            gyro_y = struct.unpack('<h', data[10:12])[0]
            gyro_z = struct.unpack('<h', data[12:14])[0]

            return gyro_x / GYRO_SCALE, gyro_y / GYRO_SCALE, gyro_z / GYRO_SCALE
        except Exception as e:
            logger.error(f"读取陀螺仪失败: {e}")
            return None, None, None

    def read_acc_gyro(self):
        """
        读取加速度和陀螺仪数据
        返回: (acc_x_g, acc_y_g, acc_z_g, gyro_x_dps, gyro_y_dps, gyro_z_dps)
        """
        if not self.is_opened:
            return None, None, None, None, None, None

        try:
            data = os.read(self.fd, 14)
            if len(data) < 14:
                return None, None, None, None, None, None

            # 解析数据（小端序）
            acc_x = struct.unpack('<h', data[0:2])[0]
            acc_y = struct.unpack('<h', data[2:4])[0]
            acc_z = struct.unpack('<h', data[4:6])[0]
            gyro_x = struct.unpack('<h', data[8:10])[0]
            gyro_y = struct.unpack('<h', data[10:12])[0]
            gyro_z = struct.unpack('<h', data[12:14])[0]

            return (acc_x / ACC_SCALE, acc_y / ACC_SCALE, acc_z / ACC_SCALE,
                    gyro_x / GYRO_SCALE, gyro_y / GYRO_SCALE, gyro_z / GYRO_SCALE)
        except Exception as e:
            logger.error(f"读取加速度和陀螺仪失败: {e}")
            return None, None, None, None, None, None

    def __enter__(self):
        """上下文管理器入口"""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


# 全局单例 - 在模块加载时创建
_accelerometer_instance = None


def get_accelerometer():
    """获取全局加速度计实例（单例模式）"""
    global _accelerometer_instance
    if _accelerometer_instance is None:
        _accelerometer_instance = ICM20689()
        # 立即尝试打开设备
        _accelerometer_instance.open()
    return _accelerometer_instance


def init_accelerometer():
    """初始化加速度计"""
    acc = get_accelerometer()
    return acc.open()


def read_acceleration():
    """
    读取加速度数据（兼容旧API）
    返回: (x, y, z) - g值
    """
    acc = get_accelerometer()
    if acc.is_opened:
        return acc.read_g()
    return None, None, None


def read_acceleration_raw():
    """
    读取加速度原始数据
    返回: (x, y, z) - int16原始值
    """
    acc = get_accelerometer()
    if acc.is_opened:
        return acc.read_raw()
    return None, None, None


def read_magnitude():
    """
    读取加速度幅值
    返回: float - 加速度合量 (g)
    """
    acc = get_accelerometer()
    if acc.is_opened:
        return acc.read_magnitude()
    return None


def read_gyro():
    """
    读取陀螺仪数据
    返回: (x_dps, y_dps, z_dps) - °/s
    """
    acc = get_accelerometer()
    if acc.is_opened:
        return acc.read_gyro()
    return None, None, None


def read_acc_gyro():
    """
    读取加速度和陀螺仪数据
    返回: (acc_x_g, acc_y_g, acc_z_g, gyro_x_dps, gyro_y_dps, gyro_z_dps)
    """
    acc = get_accelerometer()
    if acc.is_opened:
        return acc.read_acc_gyro()
    return None, None, None, None, None, None
