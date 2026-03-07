# -*- coding: UTF-8 -*-
"""
传感器模块
包含加速度传感器、姿态检测器、步数检测器等
"""

from .icm20689 import ICM20689
from .gravity_remover import GravityRemover, get_gravity_remover, remove_gravity
from .attitude import AttitudeCalculator
from .step_detector import StepDetector
from .posture_detector import PostureDetector
from .fall_detector import FallDetector
from .high_freq_sampler import (
    HighFrequencySampler,
    get_sampler,
    start_sampling,
    stop_sampling,
    get_latest_acceleration,
    get_sample_buffer,
    get_sampling_stats,
)

__all__ = [
    'ICM20689',
    'GravityRemover',
    'get_gravity_remover',
    'remove_gravity',
    'AttitudeCalculator',
    'StepDetector',
    'PostureDetector',
    'FallDetector',
    'HighFrequencySampler',
    'get_sampler',
    'start_sampling',
    'stop_sampling',
    'get_latest_acceleration',
    'get_sample_buffer',
    'get_sampling_stats',
]
