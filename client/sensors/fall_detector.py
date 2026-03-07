# -*- coding: UTF-8 -*-
"""
跌倒检测模块

参考论文：《一种基于三轴加速度的跌倒检测方法》
作者：李争

跌倒判定阈值：
- RA > 1.85g：合加速度阈值
- SA > 2.2：加速度变化率阈值
- E > 3.5：加速度能量阈值
- Dip > 0.3：方向变化阈值

跌倒判定：所有条件同时满足
"""

import time
import math
from collections import deque


class FallDetector:
    """基于《一种基于三轴加速度的跌倒检测方法》的跌倒检测器"""

    def __init__(self, config=None):
        if config is None:
            config = {
                "ra_threshold": 1.85,      # 合加速度阈值 (g)
                "sa_threshold": 2.2,        # 加速度变化率阈值
                "energy_threshold": 3.5,    # 加速度能量阈值
                "dip_threshold": 0.3,       # 方向变化阈值
                "window_size": 50,         # 分析窗口大小
            }

        self.config = config
        self.ra_threshold = config.get("ra_threshold", 1.85)
        self.sa_threshold = config.get("sa_threshold", 2.2)
        self.energy_threshold = config.get("energy_threshold", 3.5)
        self.dip_threshold = config.get("dip_threshold", 0.3)
        self.window_size = config.get("window_size", 50)

        # 数据缓冲
        self.acc_x_buffer = deque(maxlen=self.window_size)
        self.acc_y_buffer = deque(maxlen=self.window_size)
        self.acc_z_buffer = deque(maxlen=self.window_size)
        self.timestamp_buffer = deque(maxlen=self.window_size)

        # 上一帧的合加速度
        self.prev_ra = 1.0

        # 跌倒状态
        self.is_falling = False
        self.fall_start_time = None

        # 当前状态
        self.current_state = "normal"

    def check(self, acc_x, acc_y, acc_z):
        """
        检查是否跌倒

        参数:
            acc_x, acc_y, acc_z: 三轴加速度 (g)

        返回:
            (is_fall, details) - 是否跌倒及详情
        """
        current_time = time.time()

        # 添加到缓冲
        self.acc_x_buffer.append(acc_x)
        self.acc_y_buffer.append(acc_y)
        self.acc_z_buffer.append(acc_z)
        self.timestamp_buffer.append(current_time)

        # 需要足够数据
        if len(self.acc_x_buffer) < self.window_size:
            return False, {"state": "collecting", "samples": len(self.acc_x_buffer)}

        # 计算论文4的各项特征
        ra = self._calculate_ra()
        sa = self._calculate_sa()
        energy = self._calculate_energy()
        dip = self._calculate_dip()

        # 论文4跌倒判定条件
        is_fall = (ra > self.ra_threshold and
                   sa > self.sa_threshold and
                   energy > self.energy_threshold and
                   dip > self.dip_threshold)

        # 状态机处理
        if is_fall:
            if not self.is_falling:
                self.is_falling = True
                self.fall_start_time = current_time
                self.current_state = "fall_detected"
            else:
                self.current_state = "fall_confirmed"
        else:
            # 检查是否恢复（静止一段时间后）
            if self.is_falling and self.current_state == "fall_confirmed":
                # 检查静止状态
                if self._check_static():
                    self.is_falling = False
                    self.current_state = "recovered"
                else:
                    self.current_state = "fall_detected"
            else:
                self.is_falling = False
                self.current_state = "normal"

        details = {
            "state": self.current_state,
            "ra": ra,
            "sa": sa,
            "energy": energy,
            "dip": dip,
            "ra_threshold": self.ra_threshold,
            "sa_threshold": self.sa_threshold,
            "energy_threshold": self.energy_threshold,
            "dip_threshold": self.dip_threshold,
        }

        return is_fall, details

    def _calculate_ra(self):
        """计算合加速度 RA = sqrt(ax^2 + ay^2 + az^2)"""
        if not self.acc_x_buffer:
            return 1.0
        # 取窗口最后一个点
        ax = self.acc_x_buffer[-1]
        ay = self.acc_y_buffer[-1]
        az = self.acc_z_buffer[-1]
        return math.sqrt(ax**2 + ay**2 + az**2)

    def _calculate_sa(self):
        """
        计算加速度变化率 SA = (1/t) × [∫Ax(t)dt + ∫Ay(t)dt + ∫Az(t)dt]
        简化为：|RA[t] - RA[t-1]| × 采样率
        """
        if len(self.acc_x_buffer) < 2:
            return 0.0

        # 计算当前和上一帧的合加速度差值
        current_ra = self._calculate_ra()
        sa = abs(current_ra - self.prev_ra) * 50  # 50Hz采样率

        self.prev_ra = current_ra
        return sa

    def _calculate_energy(self):
        """
        计算加速度能量 E = ∫s(t)^2dt
        简化为：窗口内所有点的加速度平方和
        """
        if not self.acc_x_buffer:
            return 0.0

        energy = 0.0
        for i in range(len(self.acc_x_buffer)):
            ax = self.acc_x_buffer[i]
            ay = self.acc_y_buffer[i]
            az = self.acc_z_buffer[i]
            energy += ax**2 + ay**2 + az**2

        return energy

    def _calculate_dip(self):
        """
        计算方向变化 D = sqrt(sum((xi - yi)^2))
        简化为：相邻帧之间的方向变化
        """
        if len(self.acc_x_buffer) < 2:
            return 0.0

        # 取最后两个点
        ax1, ay1, az1 = self.acc_x_buffer[-2], self.acc_y_buffer[-2], self.acc_z_buffer[-2]
        ax2, ay2, az2 = self.acc_x_buffer[-1], self.acc_y_buffer[-1], self.acc_z_buffer[-1]

        # 计算方向变化
        diff_x = ax2 - ax1
        diff_y = ay2 - ay1

        return math.sqrt(diff_x**2 + diff_y**2)

    def _check_static(self):
        """检查是否处于静止状态"""
        if len(self.acc_x_buffer) < 10:
            return False

        # 计算方差
        recent_x = list(self.acc_x_buffer)[-10:]
        recent_y = list(self.acc_y_buffer)[-10:]
        recent_z = list(self.acc_z_buffer)[-10:]

        mean_x = sum(recent_x) / len(recent_x)
        mean_y = sum(recent_y) / len(recent_y)
        mean_z = sum(recent_z) / len(recent_z)

        var_x = sum((x - mean_x)**2 for x in recent_x) / len(recent_x)
        var_y = sum((y - mean_y)**2 for y in recent_y) / len(recent_y)
        var_z = sum((z - mean_z)**2 for z in recent_z) / len(recent_z)

        # 方差小于阈值认为是静止
        static_threshold = 0.01
        return var_x < static_threshold and var_y < static_threshold and var_z < static_threshold

    def reset(self):
        """重置检测器"""
        self.acc_x_buffer.clear()
        self.acc_y_buffer.clear()
        self.acc_z_buffer.clear()
        self.timestamp_buffer.clear()
        self.prev_ra = 1.0
        self.is_falling = False
        self.fall_start_time = None
        self.current_state = "normal"

    def get_state(self):
        """获取当前状态"""
        return self.current_state