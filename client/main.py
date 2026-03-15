# -*- coding: UTF-8 -*-
"""
行空板M10运动腰带程序

功能：
- 3种模式：生活模式、运动模式、会议模式
- 步数检测（50Hz高频采样）
- 坐姿检测（Y轴分量法+Roll角）
- 跌倒检测（多特征融合+状态机）
- 温湿度监测
- GNSS速度（用于配速计算）
- 语音播报
- 服务器通信

模块依赖：
- sensors: 传感器和检测算法模块
- utils: 调试和辅助工具模块
"""

import time
import threading
import math
import signal
import sys
import requests
import traceback
from collections import deque
from datetime import datetime, timedelta
from statistics import median

# 导入日志模块
from utils.logger import get_logger
from services import GNSSManager, GNSS_AVAILABLE, OfflineManager
from ui import RotatedMessageScroller, create_ui_elements, hide_all_ui as hide_ui_elements, update_ui_mode as apply_ui_mode
logger = get_logger('main')


_throttled_log_times = {}
_throttled_log_lock = threading.Lock()


def log_throttled(level, key, message, interval=30):
    """按 key 节流日志输出"""
    now = time.time()
    with _throttled_log_lock:
        last_time = _throttled_log_times.get(key, 0)
        if now - last_time < interval:
            return
        _throttled_log_times[key] = now

    getattr(logger, level)(message)

# ==================== 传感器模块（核心算法）====================
# 使用sensors模块版本
USE_SENSORS_MODULE = True

# 先导入config（必须在使用sensors之前）
import config

# 传感器和检测器实例 (使用icm_前缀避免与行空板内置变量冲突)
icm_accelerometer = None
step_detector = None
posture_detector = None
fall_detector = None
attitude_calculator = None

# 模块可用标志
sensors_module_available = False

try:
    from sensors import (
        ICM20689,
        AttitudeCalculator,
        StepDetector,
        PostureDetector,
        FallDetector,
        start_sampling,
        stop_sampling,
        get_sampling_stats,
    )
    sensors_module_available = True
    logger.info("使用sensors模块 (50Hz采样)")
except ImportError as e:
    sensors_module_available = False
    logger.critical(f"sensors模块加载失败: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# 高频采样器实例
sampler = None

# 初始化加速度传感器
if USE_SENSORS_MODULE and sensors_module_available:
    try:
        icm_accelerometer = ICM20689()
        if icm_accelerometer.open():
            logger.info("ICM20689初始化成功 (50Hz)")

            # 创建检测器实例（使用config中的参数）
            step_detector = StepDetector(config.STEP_CONFIG)
            posture_detector = PostureDetector(config.POSTURE_CONFIG)
            fall_detector = FallDetector()
            attitude_calculator = AttitudeCalculator()
            logger.info("检测器初始化成功")

            # 启动高频采样器（50Hz）
            if start_sampling():
                logger.info("50Hz高频采样已启动")
                # 获取采样器实例
                from sensors import get_sampler
                sampler = get_sampler()
            else:
                logger.warning("高频采样启动失败，将使用低频模式")
        else:
            logger.error("ICM20689打开失败")
            icm_accelerometer = None
    except Exception as e:
        logger.error(f"传感器初始化错误: {e}")
        icm_accelerometer = None

# 兼容层：统一加速度读取接口
def read_acceleration():
    """统一读取加速度数据 (g值) - 优先使用高频采样器"""
    global sampler

    # 优先使用高频采样器（50Hz）
    if sampler is not None:
        try:
            from sensors import get_latest_acceleration
            ax, ay, az, mag = get_latest_acceleration()
            return ax, ay, az
        except Exception:
            pass

    # 回退到直接读取
    if icm_accelerometer is not None:
        return icm_accelerometer.read_g()
    return None, None, None

def read_acceleration_raw():
    """读取原始加速度值"""
    if icm_accelerometer is not None:
        return icm_accelerometer.read_raw()
    return None, None, None

def get_acceleration_strength():
    """获取加速度幅值"""
    global sampler

    # 优先使用高频采样器
    if sampler is not None:
        try:
            from sensors import get_latest_acceleration
            ax, ay, az, mag = get_latest_acceleration()
            return mag
        except Exception:
            pass

    if icm_accelerometer is not None:
        return icm_accelerometer.read_magnitude()
    return 0

# ==================== 工具模块 ====================
try:
    from utils import DebugLogger
    from utils import calculate_pace as utils_calculate_pace
    from utils import calculate_step_and_carbon as utils_calculate_step_and_carbon
    utils_available = True
    logger.info("utils模块已加载")
except ImportError:
    utils_available = False
    logger.warning("utils模块不可用，使用内置函数")

# 辅助函数
def get_step_length_by_frequency(steps_per_second):
    """根据步频获取步长（米）

    步频分级（步/分钟）：
    - 慢走: < 110步/分钟
    - 行走: 110~140步/分钟
    - 跑步/快走: > 140步/分钟
    """
    # 转换为步/分钟
    steps_per_minute = steps_per_second * 60

    if steps_per_minute < config.STEP_FREQ_SLOW:
        return config.STEP_LENGTH_SLOW
    elif steps_per_minute <= config.STEP_FREQ_NORMAL:
        return config.STEP_LENGTH_NORMAL
    else:
        return config.STEP_LENGTH_FAST


def calculate_pace(steps=None, duration_seconds=None, steps_per_second=None):
    if utils_available:
        return utils_calculate_pace(steps, duration_seconds)
    # 内置兼容函数
    if steps is None or duration_seconds is None or steps < 10 or duration_seconds < 30:
        return "--'--\""

    # 使用步频对应的步长，如果没有提供步频则使用默认步长
    if steps_per_second is not None:
        step_length = get_step_length_by_frequency(steps_per_second)
    else:
        step_length = config.STEP_LENGTH_NORMAL

    distance_km = steps * step_length / 1000
    if distance_km < 0.01:
        return "--'--\""
    duration_min = duration_seconds / 60
    pace = duration_min / distance_km
    if pace < 3 or pace > 30:
        return "--'--\""
    minutes = int(pace)
    seconds = int((pace - minutes) * 60)
    return f"{minutes}'{seconds:02d}\""

def calculate_step_and_carbon(steps, step_length=None):
    if utils_available:
        return utils_calculate_step_and_carbon(steps)
    # 内置兼容函数
    if steps <= 0:
        return {"steps": 0, "distance_km": 0, "carbon_kg": 0}
    # 使用传入的步长或默认步长
    if step_length is None:
        step_length = config.STEP_LENGTH_NORMAL
    distance_km = steps * step_length / 1000
    carbon_kg = steps * 0.0014
    return {"steps": steps, "distance_km": round(distance_km, 2), "carbon_kg": round(carbon_kg, 4)}

# ==================== 调试日志记录器 ====================
# 使用utils模块的DebugLogger
debug_logger = DebugLogger(enabled=config.DEBUG_ENABLED, debug_dir=config.DEBUG_DIR)


# ==================== 硬件库导入 ====================
# 注意：这些只在行空板上可用
try:
    from pinpong.board import Board, Pin, DHT11, NeoPixel, ADC
    from pinpong.extension.unihiker import *
    from pinpong.libs.dfrobot_speech_synthesis import DFRobot_SpeechSynthesis_I2C
    from unihiker import GUI
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    logger.warning("硬件库不可用（可能在模拟环境中）")


# ==================== 配置 ====================
SERVER_URL = config.SERVER_URL
UPDATE_INTERVAL = config.UPDATE_INTERVAL
DEBUG_ENABLED = config.DEBUG_ENABLED
DEBUG_DIR = config.DEBUG_DIR

# 引脚配置转换
def _to_pin(pin_str):
    if isinstance(pin_str, str):
        return getattr(Pin, pin_str)
    return pin_str

PIN_DHT11 = _to_pin(config.PIN_DHT11)
PIN_TOUCH = _to_pin(config.PIN_TOUCH)
PIN_KNOB = _to_pin(config.PIN_KNOB)
PIN_LED = _to_pin(config.PIN_LED)
LED_COUNT = config.LED_COUNT

# 模式定义
MODE_LIFE = config.MODE_LIFE
MODE_SPORT = config.MODE_SPORT
MODE_MEETING = config.MODE_MEETING
MODE_NAMES = ["生活模式", "运动模式", "会议模式"]
VALID_MODES = tuple(range(len(MODE_NAMES)))
MODE_COLORS = ["#000000", "#000000", "#000000"]
LINE_COLORS = ["#00FF00", "#FFFF00", "#8888FF"]


# ==================== 全局变量 ====================
current_mode = MODE_LIFE
last_temp = 25
last_humi = 50
led_brightness = 128
emergency_mode = False
voice_queue = []
sitting_start_time = None
current_posture = "unknown"
sport_start_time = None
sport_time_today = 0
sport_duration = 0
last_activity_hour = -1
activity_hours = set()
sitting_duration = 0
fall_detected = False
running = True
voice_enabled = True
last_movement_time = None
exit_sport_countdown = False
env_auto_exit_start_time = None  # 环境恶劣自动退出开始时间
env_exit_cancelled_by_touch = False  # 环境退出是否被触摸板取消
touch_press_start = None
long_press_threshold = 2.0  # 长按阈值改为2秒
double_click_interval = 0.7  # 双击最大间隔
double_click_cooldown = 10.0  # 双击冷却时间10秒
double_click_last_time = 0  # 上次双击触发时间
last_click_time = None  # 上次点击时间
long_press_2s_voiced = False  # 长按2秒语音是否已播报
sitting_remind_duration = config.DEFAULT_SITTING_REMIND_DURATION
step_count = 0
carbon_reduce_count = 0

# 配速显示
current_pace_str = "--'--\""  # 当前配速显示
last_valid_pace_str = "--'--\""  # 最近一次有效配速
has_valid_pace = False  # 是否出现过有效配速

# 平均配速计算（用于运动记录）
sport_pace_total_distance = 0.0  # 运动期间总距离(km)
sport_pace_total_time = 0.0  # 运动期间总时间(秒)
sport_pace_start_time = None  # 第一次有效配速计时开始时间

# GPS速度读取计时器
gps_speed_read_time = None  # 上次读取GPS速度的时间
gps_current_speed = None  # 当前GPS速度(km/h)

# GNSS有效状态
gnss_valid = False  # GNSS是否有效（达到可用卫星数阈值）
gnss_last_check_time = None  # 上次检查GNSS有效性的时间
gnss_searching = False  # 是否正在搜星
gnss_search_start_time = None  # 搜星开始时间
gnss_search_thread = None  # 搜星线程
gnss_next_search_time = 0.0  # 下次允许重新搜星的时间
gnss_initial_search_done = False  # 本次运动模式是否已启动过首次搜星
gnss_search_disabled_for_session = False  # 本次运动模式是否禁止再次搜星
gnss_last_health_check_time = None  # 上次5秒卫星健康检查时间

# 步数配速计算计时器
step_pace_start_time = None  # 步数配速计算开始时间
step_pace_last_step = 0  # 上次记录的步数
step_pace_accumulated_distance = 0.0  # 步数配速累计距离
step_pace_accumulated_time = 0.0  # 步数配速累计时间
sport_session_start_step = None  # 本次运动开始时的累计步数

# 运动记录曲线（低频采样，减少算力与存储开销）
SPORT_SERIES_INTERVAL = 5.0  # 秒
sport_series = []
sport_series_last_ts = None
sport_series_last_step = 0
sport_series_last_point_ts = 0.0
sport_session_distance_km = 0.0
sport_last_stride_m = config.STEP_LENGTH_NORMAL
sport_last_cadence_spm = 0.0

GNSS_RUNTIME_CONFIG = getattr(config, 'GNSS_CONFIG', {}) or {}
GNSS_TRACK_INTERVAL = float(GNSS_RUNTIME_CONFIG.get('track_interval', 1.0))
GNSS_PACE_INTERVAL_SEC = float(GNSS_RUNTIME_CONFIG.get('pace_speed_interval_sec', 5.0))
PACE_VALID_MIN_MIN_PER_KM = float(GNSS_RUNTIME_CONFIG.get('pace_valid_min_min_per_km', 3.0))
PACE_VALID_MAX_MIN_PER_KM = float(GNSS_RUNTIME_CONFIG.get('pace_valid_max_min_per_km', 8.0))
GNSS_SEARCH_RETRY_INTERVAL = float(GNSS_RUNTIME_CONFIG.get('search_retry_interval', 15.0))
GNSS_HEALTH_CHECK_INTERVAL_SEC = 5.0
sport_gnss_track = []
sport_gnss_last_point = None
sport_gnss_last_track_ts = 0.0
sport_gnss_distance_km = 0.0
sport_gnss_fix_samples = 0
sport_gnss_total_samples = 0
sport_gnss_satellite_max = 0
sport_gnss_latest_point = None
sport_gnss_last_step_count = None

# UI元素
ui_elements = {}
message_showing = False
current_message = ""
message_scroller = None
meeting_black_rect = None

# 步数记录
last_sent_step = 0
led_position = 0


def _set_message_scroller_state(is_showing, message):
    """同步滚动消息状态到主程序全局变量"""
    global message_showing, current_message
    message_showing = is_showing
    current_message = message


def ensure_message_scroller():
    """按需创建滚动消息控制器"""
    global message_scroller

    if message_scroller is None:
        scroll_config = getattr(config, 'MESSAGE_SCROLL_CONFIG', {})
        message_scroller = RotatedMessageScroller(
            gui_getter=lambda: gui,
            hide_ui_callback=hide_all_ui,
            restore_ui_callback=update_ui_mode,
            speak_callback=add_voice,
            stop_voice_callback=stop_all_voice,
            is_running_callback=lambda: running,
            is_emergency_callback=lambda: emergency_mode,
            state_change_callback=_set_message_scroller_state,
            text_x=scroll_config.get('text_x', 0),
            font_size=scroll_config.get('font_size', 129),
            scroll_speed=scroll_config.get('scroll_speed', 74.0),
            frame_time=scroll_config.get('frame_time', 0.033),
            start_offset_ratio=scroll_config.get('start_offset_ratio', 0.9),
            initial_y_compensation=scroll_config.get('initial_y_compensation', 0),
            tail_gap_ratio=scroll_config.get('tail_gap_ratio', 0.25),
            min_tail_gap=scroll_config.get('min_tail_gap', 12),
        )
    return message_scroller


def restore_today_stats_from_server():
    """启动时从服务端恢复今日统计，避免设备端与服务端口径不一致"""
    global step_count, carbon_reduce_count, sport_time_today, activity_hours

    try:
        response = requests.get(f"{SERVER_URL}/api/status", timeout=5)
        if response.status_code != 200:
            logger.info(f"服务端今日统计恢复跳过: HTTP {response.status_code}")
            return False

        data = response.json() or {}
        restored_step = max(0, int(data.get("step", 0) or 0))
        restored_carbon = round(float(data.get("carbon_reduce", 0) or 0), 2)
        restored_sport_time = max(0, int(data.get("sport_time_today", 0) or 0))

        restored_hours = set()
        for hour in data.get("activity_hours", []) or []:
            try:
                hour_value = int(hour)
                if 0 <= hour_value <= 23:
                    restored_hours.add(hour_value)
            except Exception:
                pass

        step_count = restored_step
        carbon_reduce_count = max(0, restored_carbon)
        sport_time_today = restored_sport_time
        activity_hours = restored_hours

        if step_detector:
            try:
                step_detector.set_count(step_count)
            except Exception as e:
                logger.warning(f"恢复今日步数后设置检测器失败: {e}")

        logger.info(
            f"已从服务端恢复今日统计: 步数={step_count}, 减碳={carbon_reduce_count}g, "
            f"运动时长={sport_time_today}s"
        )
        return True
    except Exception as e:
        logger.info(f"服务端今日统计恢复失败，继续使用本地计数: {e}")
        return False


def is_valid_mode(mode):
    """判断模式值是否合法"""
    return isinstance(mode, int) and mode in VALID_MODES


# ==================== 退出处理 ====================
def exit_handler(signum=None, frame=None):
    """程序退出处理"""
    global running
    logger.info("正在清理资源...")
    running = False

    try:
        # 停止高频采样器
        if sampler is not None:
            from sensors import stop_sampling
            stop_sampling()
            logger.info("高频采样已停止")

        if led_strip:
            for i in range(LED_COUNT):
                led_strip[i] = (0, 0, 0)
        if gui:
            gui.clear()
        debug_logger.stop()
        logger.info("清理完成，程序退出")
    except:
        pass

    sys.exit(0)

signal.signal(signal.SIGINT, exit_handler)
signal.signal(signal.SIGTERM, exit_handler)


# ==================== 硬件对象 ====================
dht11 = None
touch = None
knob = None
led_strip = None
tts = None
gui = None


# ==================== UI初始化 ====================
def init_ui():
    """初始化UI - 创建所有模式的UI元素"""
    global ui_elements

    if not gui:
        return

    gui.clear()
    ui_elements = create_ui_elements(gui)
    update_ui_mode()


def update_ui_mode():
    """根据模式更新UI显示 - 隐藏/显示方式"""
    apply_ui_mode(
        ui_elements=ui_elements,
        current_mode=current_mode,
        message_showing=message_showing,
        mode_life=MODE_LIFE,
        mode_sport=MODE_SPORT,
        mode_meeting=MODE_MEETING,
    )


def hide_all_ui():
    """隐藏所有UI元素"""
    hide_ui_elements(ui_elements)


# ==================== 环境状态判断 ====================
def get_environment_status():
    """获取环境状态，返回(状态列表, 语音播报文本，警告等级)"""
    global last_temp, last_humi

    temp_status = []
    humi_status = []

    try:
        if dht11:
            temp = round(dht11.temp_c() * 0.8, 1)
            humi = dht11.humidity()
            if temp is not None and humi is not None:
                last_temp = temp
                last_humi = humi
    except:
        pass

    temp = last_temp
    humi = last_humi

    # 温度判断
    if temp < 0:
        temp_status = ["严寒"]
    elif 0 <= temp < 10:
        temp_status = ["寒冷"]
    elif 10 <= temp < 18:
        temp_status = ["偏冷"]
    elif 18 <= temp <= 25:
        temp_status = ["适宜"]
    elif 25 < temp <= 30:
        temp_status = ["偏热"]
    elif temp > 30:
        temp_status = ["炎热"]

    # 湿度判断（温度>26时闷热优先）
    if temp > 26:
        if humi > 65:
            humi_status = ["闷热"]
        elif 45 <= humi <= 65:
            pass  # 适宜
        elif 30 <= humi < 45:
            humi_status = ["较干"]
        else:  # <30
            humi_status = ["干燥"]
    else:
        if humi < 30:
            humi_status = ["干燥"]
        elif 30 <= humi < 45:
            humi_status = ["较干"]
        elif 45 <= humi <= 65:
            pass  # 适宜
        elif 65 < humi <= 80:
            humi_status = ["较湿"]
        else:  # >80
            humi_status = ["潮湿"]

    # 合并状态（过滤"适宜"）
    all_status = temp_status + humi_status
    all_status = [s for s in all_status if s != "适宜"]

    # 生成播报文本
    voice_text = ""
    if not all_status:
        voice_text = "当前环境状态适宜"
    else:
        # 有警报
        temp_tip_level = 0
        humi_tip_level = 0

        if any(s in ['寒冷', '偏冷'] for s in  temp_status):
            temp_tip_level = -1
        elif any(s == '偏热' for s in  temp_status):
            temp_tip_level = 1
        elif any(s == '严寒' for s in  temp_status):
            temp_tip_level = -2
        elif any(s == '炎热' for s in  temp_status):
            temp_tip_level = -2

        if any(s in ['较干', '干燥'] for s in  humi_status):
            humi_tip_level = 1
        elif any(s in ['较湿', '潮湿'] for s in  humi_status):
            humi_tip_level = 2

        # 播报温度
        if temp_tip_level != 0:
            if temp_tip_level < 0:
                voice_text += f"当前温度{int(temp)}度，请注意保暖"
            else:
                voice_text += f"当前温度{int(temp)}度，请注意降温"

        # 播报湿度
        if humi_tip_level:
            if humi_tip_level == 1:
                voice_text += f"当前湿度{int(humi)}%，请注意补水"
            else:
                voice_text += f"当前湿度{int(humi)}%，请注意防潮"

    return all_status, voice_text


def is_environment_warning():
    """判断环境是否不适合运动（超过"较x"范围）"""
    global last_temp, last_humi

    temp = last_temp
    humi = last_humi

    # 温度：>30°C 或 <10°C 不适合运动
    if temp > 30 or temp < 10:
        return True, "温度"
    # 湿度：>80% 或 <30% 不适合运动
    if humi > 80 or humi < 30:
        return True, "湿度"

    return False, None


def _check_and_handle_sport_environment():
    """检查运动环境条件并处理（用户规则）- 非阻塞方式"""
    global last_temp, last_humi, current_mode, env_auto_exit_start_time

    # 如果已经在倒计时中，不再重复触发
    if env_auto_exit_start_time is not None:
        return

    temp = last_temp
    humi = last_humi

    # 严重级别警报
    severe_temp = ["严寒", "炎热"]  # temp < 0 或 temp > 30
    severe_humi = ["干燥", "潮湿"]  # humi < 30 或 humi > 80

    # 一般级别警报
    general_temp = ["偏冷", "偏热"]  # 10 <= temp < 18 或 25 < temp <= 30
    general_humi = ["较干", "较湿", "闷热"]  # 各种湿度问题

    # 获取当前状态
    env_status, _ = get_environment_status()

    # 判断严重级别
    has_severe = any(s in severe_temp for s in env_status) or any(s in severe_humi for s in env_status)

    # 判断一般级别
    has_general = any(s in general_temp for s in env_status) or any(s in general_humi for s in env_status)

    # 适宜（无警报）
    is_ideal = len(env_status) == 0

    if is_ideal:
        # 适宜：当前环境状态适宜，运动条件良好
        add_voice("当前环境状态适宜，运动条件良好")
    elif has_severe:
        # 严重级别：生成播报文本并设置15秒倒计时
        voice_text = ""
        if temp < 0:
            voice_text += f"当前严寒，气温{int(temp)}度，"
        elif temp > 30:
            voice_text += f"当前炎热，气温{int(temp)}度，"

        if humi < 30:
            voice_text += f"当前干燥，湿度{int(humi)}%，"
        elif humi > 80:
            voice_text += f"当前潮湿，湿度{int(humi)}%，"

        voice_text += "运动条件恶劣，不建议继续运动，即将在5秒后退出运动模式，长按取消退出"
        add_voice(voice_text)

        # 设置15秒倒计时（非阻塞）
        env_auto_exit_start_time = time.time()
    elif has_general:
        # 一般级别：播报具体问题 + 不建议长时间运动
        voice_text = ""
        if "偏冷" in env_status or "偏热" in env_status:
            if "偏冷" in env_status:
                voice_text += f"当前温度{int(temp)}度，偏冷，"
            if "偏热" in env_status:
                voice_text += f"当前温度{int(temp)}度，偏热，"

        if "较干" in env_status or "较湿" in env_status or "闷热" in env_status:
            if "较干" in env_status:
                voice_text += f"当前湿度{int(humi)}%，较干，"
            if "较湿" in env_status:
                voice_text += f"当前湿度{int(humi)}%，较湿，"
            if "闷热" in env_status:
                voice_text += f"当前环境闷热，"

        voice_text += "不建议长时间运动"
        add_voice(voice_text)


# ==================== 状态播报 ====================
def report_life_mode_status():
    """生活模式双击播报"""
    global last_temp, last_humi, sitting_duration

    # 环境状态
    _, voice_text = get_environment_status()
    if voice_text:
        add_voice(voice_text)

    # 坐姿提醒
    sitting_min = sitting_duration // 60
    if sitting_min >= 30:
        add_voice(f"您已保持坐姿超过{sitting_min}分钟，建议起来活动一会")

    # 当前时间（口语化）
    now = datetime.now()
    time_str = f"{now.hour}时{now.minute}分"
    add_voice(f"当前时间{time_str}")


def report_sport_mode_status():
    """运动模式双击播报"""
    global last_temp, last_humi, step_count, carbon_reduce_count, current_pace_str

    # 环境警告
    is_warning, warn_type = is_environment_warning()
    if is_warning:
        if warn_type == "温度":
            add_voice(f"当前温度{int(last_temp)}度，不建议继续运动")
        else:
            add_voice(f"当前湿度{int(last_humi)}度，不建议继续运动")

    # 配速（使用GPS速度计算的配速）
    if current_pace_str != "--'--\"":
        add_voice(f"当前配速{current_pace_str}")

    # 步数
    add_voice(f"当前步数{step_count}步")

    # 减碳（播报）
    carbon_kg = carbon_reduce_count / 1000
    if carbon_kg >= 1:
        carbon_str = f"{round(carbon_kg, 2)}千克"
    else:
        # <1kg时显示克，精确到整数
        carbon_str = f"{int(carbon_reduce_count)}克"
    add_voice(f"您已累计减碳{carbon_str}，感谢您为保护环境做出的贡献")


# ==================== 消息滚动显示 ====================
def show_message_scroll(message):
    """显示滚动消息"""
    ensure_message_scroller().show(message)


def exit_message_scroll():
    """退出消息滚动"""
    ensure_message_scroller().hide()


# ==================== 语音合成 ====================
def add_voice(text, force=False):
    """添加语音到队列"""
    if not voice_enabled:
        return

    if current_mode == MODE_MEETING and not force:
        logger.debug(f"会议模式静音，跳过语音: {text}")
        return

    voice_queue.append({"text": text, "force": force})
    logger.info(f"语音播报: {text}")


def stop_all_voice():
    """停止所有语音"""
    voice_queue.clear()
    try:
        if tts:
            tts.stop()
    except:
        pass


def voice_thread():
    """语音播报线程"""
    while running:
        if voice_queue and voice_enabled:
            item = voice_queue.pop(0)
            text = item.get("text", "") if isinstance(item, dict) else item
            try:
                if tts:
                    tts.speak(text)
                    time.sleep(0.2)
                else:
                    logger.warning(f"[语音] tts对象为空，无法播放: {text}")
            except Exception as e:
                logger.error(f"语音播放错误: {e}")
        time.sleep(0.1)


# ==================== LED控制 ====================
# LED状态变量
led_sport_state = 0  # 0: 奇数灯, 1: 偶数灯
led_sport_thread = None
led_sport_running = False

# SOS摩斯电码：短=0.2s, 长=0.6s, 间隔=0.2s, 字母间隔=0.6s
SOS_PATTERN = [
    (0.2, True), (0.2, False), (0.2, True), (0.2, False), (0.2, True),  # S: ...
    (0.6, False),  # 字母间隔
    (0.6, True), (0.6, False), (0.6, True), (0.6, False), (0.6, True),  # O: 3长（原错误写成4长）
    (0.6, False),  # 字母间隔
    (0.2, True), (0.2, False), (0.2, True), (0.2, False), (0.2, True),  # S: ...
    (1.0, False),  # 单词间隔
]
led_sos_thread = None
led_sos_running = False


def set_led_color(r, g, b):
    """设置所有LED颜色"""
    try:
        if led_strip:
            for i in range(LED_COUNT):
                led_strip[i] = (int(r), int(g), int(b))
    except:
        pass


def set_led_by_index(indices, r, g, b):
    """根据灯号设置LED颜色"""
    try:
        if led_strip:
            for i in indices:
                if 0 <= i < LED_COUNT:
                    led_strip[i] = (int(r), int(g), int(b))
    except:
        pass


def clear_all_led():
    """关闭所有LED"""
    set_led_color(0, 0, 0)


def led_breathe(indices, r, g, b, fade_in=True, duration=0.5):
    """LED渐变效果（非阻塞）"""
    steps = 15  # 减少步数让闪烁更快
    interval = duration / steps

    for i in range(steps + 1):
        if not led_sport_running:
            return

        # 计算当前亮度
        if fade_in:
            brightness = i / steps
        else:
            brightness = (steps - i) / steps

        brightness = max(0, min(1, brightness))

        # 设置指定灯的亮度
        try:
            if led_strip:
                for idx in indices:
                    if 0 <= idx < LED_COUNT:
                        led_strip[idx] = (
                            int(r * brightness),
                            int(g * brightness),
                            int(b * brightness)
                        )
        except:
            pass

        time.sleep(interval)


def led_breathing_thread():
    """运动模式呼吸灯线程（非阻塞）"""
    global led_sport_state, led_sport_running

    led_sport_running = True
    color = (255, 255, 0)  # 黄色

    # 渐亮和渐灭时间相同（0.5秒），交替闪烁不同时亮起
    fade_duration = 0.3

    while led_sport_running and running:
        # 检查是否退出运动模式或进入紧急模式
        if current_mode != MODE_SPORT or emergency_mode:
            # 退出运动模式或紧急模式，停止呼吸灯
            clear_all_led()
            break

        # 获取奇数/偶数灯号（1,3,5,7... 和 2,4,6,8...）
        odd_indices = [i for i in range(LED_COUNT) if i % 2 == 0]  # 0,2,4,6... (奇数灯号1,3,5,7...)
        even_indices = [i for i in range(LED_COUNT) if i % 2 == 1]  # 1,3,5,7... (偶数灯号2,4,6,8...)

        if led_sport_state == 0:
            # 奇数灯渐亮
            led_breathe(odd_indices, *color, fade_in=True, duration=fade_duration)
            # 奇数灯渐灭
            led_breathe(odd_indices, *color, fade_in=False, duration=fade_duration)
            led_sport_state = 1
        else:
            # 偶数灯渐亮
            led_breathe(even_indices, *color, fade_in=True, duration=fade_duration)
            # 偶数灯渐灭
            led_breathe(even_indices, *color, fade_in=False, duration=fade_duration)
            led_sport_state = 0

        # 短暂停顿再切换到下一组灯
        time.sleep(0.1)


def led_flash(r, g, b, interval=0.5):
    """LED闪烁效果（阻塞，用于紧急模式）"""
    set_led_color(r, g, b)
    time.sleep(interval)
    set_led_color(0, 0, 0)
    time.sleep(interval)


def led_sos_thread_func():
    """紧急模式SOS闪烁线程（非阻塞）"""
    global led_sos_running

    led_sos_running = True
    r, g, b = 255, 0, 0  # 红色

    # 紧急模式下强制最大亮度
    try:
        if led_strip:
            led_strip.brightness(255)
    except:
        pass

    while led_sos_running and running:
        for duration, is_on in SOS_PATTERN:
            if not led_sos_running or not running:
                break
            if is_on:
                # 紧急模式直接设置最高亮度，忽略旋钮调节
                set_led_color(r, g, b)
            else:
                clear_all_led()
            time.sleep(duration)


def start_led_breathing():
    """启动运动模式呼吸灯"""
    global led_sport_thread, led_sport_running

    if led_sport_thread and led_sport_thread.is_alive():
        return

    led_sport_running = True
    led_sport_thread = threading.Thread(target=led_breathing_thread, daemon=True)
    led_sport_thread.start()


def stop_led_breathing():
    """停止运动模式呼吸灯"""
    global led_sport_running, led_sos_running

    led_sport_running = False
    led_sos_running = False
    clear_all_led()


def start_led_sos():
    """启动SOS闪烁"""
    global led_sos_thread

    if led_sos_thread and led_sos_thread.is_alive():
        return

    led_sos_thread = threading.Thread(target=led_sos_thread_func, daemon=True)
    led_sos_thread.start()


def update_led_by_temp_humi(temp, humi):
    """根据温湿度返回LED颜色"""
    if temp < 20:
        return (0, 0, 255)
    elif temp < 25:
        return (0, 255, 0)
    elif temp < 30:
        return (255, 255, 0)
    else:
        return (255, 0, 0)


# ==================== 运动检测功能 ====================
def detect_step():
    """检测步数 - 处理采样器缓冲区中的所有数据"""
    global step_count, carbon_reduce_count

    if not step_detector:
        return False, {}

    detected = False
    last_step_count = step_detector.get_step_count() if step_detector else 0
    step_record = {}

    try:
        # 如果使用高频采样器，处理所有缓冲的采样点
        if sampler is not None:
            try:
                from sensors import get_sample_buffer
                buffer = get_sample_buffer()
                if buffer:
                    # 处理缓冲区中的所有采样点
                    for sample in buffer:
                        # 使用已经过重力去除的线性加速度（50Hz采样 + 重力去除）
                        linear_x = sample.get('linear_x', 0)
                        linear_y = sample.get('linear_y', 0)
                        linear_z = sample.get('linear_z', 0)
                        detected, step_record = step_detector.add_sample(
                            linear_x,
                            linear_y,
                            linear_z,
                            None,
                            None,
                            None,
                            timestamp=sample.get('timestamp'),
                            already_linear=True,
                            raw_acc=(sample.get('ax', linear_x), sample.get('ay', linear_y), sample.get('az', linear_z))
                        )

                    # 清空缓冲区
                    sampler.clear_buffer()
            except Exception as e:
                # 回退到单点读取
                ax, ay, az = read_acceleration()
                if ax is not None:
                    # 尝试读取陀螺仪
                    try:
                        from sensors.icm20689 import read_gyro
                        gx, gy, gz = read_gyro()
                        if gx is None:
                            gx, gy, gz = 0, 0, 0
                    except:
                        gx, gy, gz = 0, 0, 0
                    detected, step_record = step_detector.add_sample(ax, ay, az, gx, gy, gz)
        else:
            # 未使用采样器，直接读取
            ax, ay, az = read_acceleration()
            if ax is not None:
                # 尝试读取陀螺仪
                try:
                    from sensors.icm20689 import read_gyro
                    gx, gy, gz = read_gyro()
                    if gx is None:
                        gx, gy, gz = 0, 0, 0
                except:
                    gx, gy, gz = 0, 0, 0
                detected, step_record = step_detector.add_sample(ax, ay, az, gx, gy, gz)

        # 获取检测结果
        step_count = step_detector.get_step_count()
        carbon_reduce_count = step_count * config.CARBON_PER_STEP

        # 获取统计信息
        stats = step_detector.get_current_stats()

        # 如果检测到新步数，打印日志
        step_increase = step_count - last_step_count
        if step_increase > 0:
            logger.info(f"步数+{step_increase}，当前步数: {step_count}")

        # 获取当前加速度数据用于日志
        ax, ay, az = read_acceleration()
        if ax is not None:
            import math
            acc_mag = math.sqrt(ax**2 + ay**2 + az**2)

            # 从 record 中获取阈值信息，如果没有则用 stats 中的默认值
            threshold_upper = step_record.get('threshold_upper', stats.get('threshold_upper', 1.5))
            threshold_lower = step_record.get('threshold_lower', stats.get('threshold_lower', -0.5))

            # 记录调试日志
            debug_logger.log_step(
                ax, ay, az, acc_mag,
                threshold_upper,
                threshold_lower,
                stats.get('mean_acc', 0),
                stats.get('std_acc', 0),
                detected
            )

    except Exception as e:
        logger.error(f"步数检测错误: {e}")

    return detected, step_record


def detect_posture():
    """检测姿态"""
    global current_posture

    if not posture_detector:
        return False, "unknown"

    try:
        ax, ay, az = read_acceleration()
        if ax is not None:
            import math
            acc_mag = math.sqrt(ax**2 + ay**2 + az**2)
            pitch, roll = posture_detector.get_attitude()
            motion_level = posture_detector.get_motion_level()

            changed, new_posture = posture_detector.update(ax, ay, az)
            if changed and new_posture != current_posture:
                current_posture = new_posture
                logger.info(f"姿态切换 → {current_posture}")

            # 获取当前实际姿态（使用检测器内部状态）
            posture_result = posture_detector.get_posture()

            # 记录调试日志
            debug_logger.log_posture(
                ax, ay, az, acc_mag,
                pitch, roll, posture_result, motion_level
            )

            return changed, posture_result
    except Exception as e:
        logger.error(f"姿态检测错误: {e}")

    return False, "unknown"


def detect_fall():
    """检测跌倒"""
    global fall_detector

    if not fall_detector:
        return False

    try:
        ax, ay, az = read_acceleration()
        if ax is not None:
            import math
            acc_mag = math.sqrt(ax**2 + ay**2 + az**2)
            pitch, roll = 0, 0
            if attitude_calculator:
                pitch, roll = attitude_calculator.update(ax, ay, az)

            # 传递加速度数据给跌倒检测器（论文4方法）
            is_fall, state = fall_detector.check(ax, ay, az)

            # 记录跌倒调试数据
            debug_logger.log_fall(
                ax, ay, az, acc_mag, pitch, roll,
                state.get('state', 'unknown') if state else 'unknown',
                state.get('variance', 0) if state else 0,
                state.get('peak_acc', 0) if state else 0,
                state.get('min_acc', 0) if state else 0,
                state.get('angle_change', 0) if state else 0
            )

            return is_fall
    except Exception as e:
        logger.error(f"跌倒检测错误: {e}")
        return False

    return False


def trigger_fall_alarm():
    """统一触发跌倒告警流程"""
    global fall_detected

    if fall_detected:
        return

    logger.warning("检测到摔倒！")
    fall_detected = True
    stop_all_voice()
    add_voice("检测到摔倒，是否需要帮助？长按取消警报")
    threading.Thread(target=emergency_countdown, daemon=True).start()


def detect_movement():
    """检测是否有运动"""
    global last_movement_time
    try:
        acc_strength = get_acceleration_strength()
        if acc_strength and acc_strength > 1.3:
            last_movement_time = time.time()
            return True
    except:
        pass
    return False


# ==================== 运动时长统计 ====================
last_update_time = None


def _pace_str_to_sec_per_km(pace_str):
    """将配速字符串 m'ss\" 转为 sec/km，非法返回 None"""
    if not pace_str or pace_str.startswith("--"):
        return None
    try:
        parts = pace_str.replace('"', '').split("'")
        if len(parts) != 2:
            return None
        minutes = int(parts[0])
        seconds = int(parts[1])
        if minutes < 0 or seconds < 0 or seconds >= 60:
            return None
        return minutes * 60 + seconds
    except Exception:
        return None


def _is_valid_running_pace(pace_min_per_km):
    """按运行配速范围判断是否为有效值"""
    if pace_min_per_km is None:
        return False
    try:
        pace_min_per_km = float(pace_min_per_km)
    except (TypeError, ValueError):
        return False
    return PACE_VALID_MIN_MIN_PER_KM <= pace_min_per_km <= PACE_VALID_MAX_MIN_PER_KM


def _reset_sport_gnss_state(now=None):
    """重置运动会话的 GNSS 轨迹状态"""
    global sport_gnss_track, sport_gnss_last_point, sport_gnss_last_track_ts
    global sport_gnss_distance_km, sport_gnss_fix_samples, sport_gnss_total_samples
    global sport_gnss_satellite_max, sport_gnss_latest_point, sport_gnss_last_step_count

    if now is None:
        now = time.time()

    sport_gnss_track = []
    sport_gnss_last_point = None
    sport_gnss_last_track_ts = 0.0
    sport_gnss_distance_km = 0.0
    sport_gnss_fix_samples = 0
    sport_gnss_total_samples = 0
    sport_gnss_satellite_max = 0
    sport_gnss_latest_point = None
    sport_gnss_last_step_count = None


def _should_use_gnss_distance():
    """满足条件时优先使用 GNSS 距离"""
    return sport_gnss_distance_km > 0 and len(sport_gnss_track) >= 3


def _update_gnss_track(sat_count=0, now=None):
    """按秒更新一次 GNSS 轨迹点"""
    global sport_gnss_track, sport_gnss_last_point, sport_gnss_last_track_ts
    global sport_gnss_distance_km, sport_gnss_fix_samples, sport_gnss_total_samples
    global sport_gnss_satellite_max, sport_gnss_latest_point, sport_gnss_last_step_count
    global sport_last_stride_m, sport_last_cadence_spm

    if now is None:
        now = time.time()

    if not GNSS_AVAILABLE or not gnss_manager or not gnss_manager.is_active:
        return

    sat_count = int(sat_count or 0)
    sport_gnss_total_samples += 1
    sport_gnss_satellite_max = max(sport_gnss_satellite_max, sat_count)

    if not gnss_manager.has_valid_fix(sat_count):
        return

    sport_gnss_fix_samples += 1
    if sport_gnss_last_track_ts and (now - sport_gnss_last_track_ts) < GNSS_TRACK_INTERVAL:
        return

    point = gnss_manager.get_track_point(sat_count=sat_count)
    if not point:
        return

    point['t'] = int(now - sport_start_time) if sport_start_time else int(sport_duration)

    if sport_gnss_last_point is None:
        point['distance_km'] = 0.0
        point['step_count'] = step_count
        sport_gnss_track.append(point)
        sport_gnss_last_point = point
        sport_gnss_last_track_ts = now
        sport_gnss_last_step_count = step_count
        sport_gnss_latest_point = point
        return

    delta_km = gnss_manager.haversine_distance_km(
        sport_gnss_last_point.get('lat'),
        sport_gnss_last_point.get('lon'),
        point.get('lat'),
        point.get('lon'),
    )
    delta_m = delta_km * 1000.0

    if delta_m <= 0:
        return

    min_move_distance_m = float(GNSS_RUNTIME_CONFIG.get('min_move_distance_m', 0.8))
    max_jump_distance_m = float(GNSS_RUNTIME_CONFIG.get('max_jump_distance_m', 35.0))
    max_jump_speed_kmh = float(GNSS_RUNTIME_CONFIG.get('max_jump_speed_kmh', 25.0))

    elapsed = max(now - sport_gnss_last_track_ts, 1e-6)
    estimated_speed_kmh = (delta_km / elapsed) * 3600.0
    point_speed_kmh = point.get('speed_kmh')

    if delta_m < min_move_distance_m:
        return
    if delta_m > max_jump_distance_m:
        return
    if point_speed_kmh is not None and point_speed_kmh > max_jump_speed_kmh:
        return
    if estimated_speed_kmh > max_jump_speed_kmh:
        return

    sport_gnss_distance_km += delta_km
    point['distance_km'] = round(sport_gnss_distance_km, 3)

    delta_steps = max(0, step_count - int(sport_gnss_last_step_count or 0))
    if delta_steps > 0:
        cadence_spm = round((delta_steps / elapsed) * 60.0, 1)
        stride_m = delta_m / delta_steps
        if 0.2 <= stride_m <= 2.5:
            point['stride_m'] = round(stride_m, 2)
            point['cadence_spm'] = cadence_spm
            sport_last_stride_m = point['stride_m']
            sport_last_cadence_spm = cadence_spm

    point['step_count'] = step_count
    sport_gnss_track.append(point)
    sport_gnss_last_point = point
    sport_gnss_last_track_ts = now
    sport_gnss_last_step_count = step_count
    sport_gnss_latest_point = point


def _reset_sport_series(now=None):
    """开始新的运动会话时，重置曲线与累计距离"""
    global sport_series, sport_series_last_ts, sport_series_last_step, sport_series_last_point_ts
    global sport_session_distance_km, sport_last_stride_m, sport_last_cadence_spm

    if now is None:
        now = time.time()

    sport_series = []
    sport_series_last_ts = now
    sport_series_last_step = step_count
    sport_series_last_point_ts = 0.0
    sport_session_distance_km = 0.0
    sport_last_stride_m = config.STEP_LENGTH_NORMAL
    sport_last_cadence_spm = 0.0
    _reset_sport_gnss_state(now)


def _update_sport_series(now=None, force_point=False):
    """更新运动曲线与累计距离（低频采样）"""
    global sport_series_last_ts, sport_series_last_step, sport_series_last_point_ts
    global sport_session_distance_km, sport_last_stride_m, sport_last_cadence_spm

    if now is None:
        now = time.time()

    if sport_series_last_ts is None:
        sport_series_last_ts = now
        sport_series_last_step = step_count
        sport_series_last_point_ts = 0.0
        return

    dt = now - sport_series_last_ts
    ds = step_count - sport_series_last_step
    if ds < 0:
        ds = step_count

    step_stride_m = None
    if dt > 0 and ds > 0:
        steps_per_second = ds / dt
        sport_last_cadence_spm = round(steps_per_second * 60, 1)
        step_stride_m = get_step_length_by_frequency(steps_per_second)
        sport_session_distance_km += (ds * step_stride_m) / 1000

    if sport_gnss_latest_point and sport_gnss_latest_point.get('stride_m') is not None:
        sport_last_stride_m = sport_gnss_latest_point.get('stride_m')
        if sport_gnss_latest_point.get('cadence_spm') is not None:
            sport_last_cadence_spm = sport_gnss_latest_point.get('cadence_spm')
    elif step_stride_m is not None:
        sport_last_stride_m = step_stride_m

    sport_series_last_ts = now
    sport_series_last_step = step_count

    if not force_point and (now - sport_series_last_point_ts) < SPORT_SERIES_INTERVAL:
        return

    session_steps = max(0, step_count - (sport_session_start_step or 0))
    carbon_g = round(session_steps * config.CARBON_PER_STEP, 2)
    pace_sec_per_km = _pace_str_to_sec_per_km(current_pace_str)
    t = int(now - sport_start_time) if sport_start_time else int(sport_duration)

    distance_km = round(sport_session_distance_km, 3)
    distance_source = 'step'
    if _should_use_gnss_distance():
        distance_km = round(sport_gnss_distance_km, 3)
        distance_source = 'gnss'

    point = {
        "t": t,
        "pace_sec_per_km": pace_sec_per_km,
        "cadence_spm": sport_last_cadence_spm,
        "stride_m": round(sport_last_stride_m, 2),
        "carbon_reduce": carbon_g,
        "distance_km": distance_km,
        "distance_source": distance_source,
    }

    if sport_gnss_latest_point:
        lat = sport_gnss_latest_point.get('lat')
        lon = sport_gnss_latest_point.get('lon')
        if lat is not None and lon is not None:
            point['lat'] = lat
            point['lon'] = lon
        if sport_gnss_latest_point.get('satellites') is not None:
            point['satellites'] = sport_gnss_latest_point.get('satellites')
        if sport_gnss_latest_point.get('speed_kmh') is not None:
            point['gnss_speed_kmh'] = sport_gnss_latest_point.get('speed_kmh')
        if sport_gnss_latest_point.get('heading_deg') is not None:
            point['heading_deg'] = sport_gnss_latest_point.get('heading_deg')
        point['gnss_distance_km'] = round(sport_gnss_distance_km, 3)

    sport_series.append(point)
    sport_series_last_point_ts = now


def update_sport_time():
    """更新运动时长"""
    global sport_start_time, sport_time_today, sport_duration, last_update_time, sport_session_start_step

    if current_mode == MODE_SPORT:
        if sport_start_time is None:
            sport_start_time = time.time()
            last_update_time = time.time()
            sport_duration = 0
            sport_session_start_step = step_count
            _reset_sport_series(sport_start_time)
        else:
            now = time.time()
            elapsed = int(now - last_update_time)

            if elapsed > 0:
                sport_time_today += elapsed
                sport_duration += elapsed
                last_update_time = now
    else:
        if sport_start_time is not None and sport_duration > 30:
            record_sport_session()
        sport_start_time = None
        last_update_time = None
        sport_duration = 0


def record_sport_session():
    """记录运动会话"""
    global sport_duration, sport_pace_total_distance, sport_pace_total_time, sport_session_start_step
    global sport_session_distance_km, sport_series
    global sport_gnss_track, sport_gnss_distance_km, sport_gnss_fix_samples
    global sport_gnss_total_samples, sport_gnss_satellite_max

    if sport_duration > 30:
        try:
            _update_sport_series(force_point=True)

            # 计算平均配速：总距离/总时间
            if sport_pace_total_time > 0 and sport_pace_total_distance > 0:
                # 配速 = 时间(分钟) / 距离(公里)
                pace_min_per_km = (sport_pace_total_time / 60) / sport_pace_total_distance
                if 3 <= pace_min_per_km <= 30:
                    pace = f"{int(pace_min_per_km)}'{int((pace_min_per_km - int(pace_min_per_km)) * 60):02d}\""
                else:
                    pace = "--'--\""
            else:
                pace = "--'--\""

            session_step_count = max(0, step_count - (sport_session_start_step or 0))
            session_carbon_reduce = round(session_step_count * config.CARBON_PER_STEP, 2)

            step_distance_km = float(sport_session_distance_km or 0.0)
            gnss_distance_km = float(sport_gnss_distance_km or 0.0)
            session_distance_km = step_distance_km
            distance_source = 'step'
            if _should_use_gnss_distance():
                session_distance_km = gnss_distance_km
                distance_source = 'gnss'

            gnss_valid_ratio = round(
                sport_gnss_fix_samples / sport_gnss_total_samples, 3
            ) if sport_gnss_total_samples > 0 else 0.0
            avg_cadence_spm = round((session_step_count / sport_duration) * 60, 1) if sport_duration > 0 else 0.0
            if session_step_count > 0:
                if session_distance_km <= 0:
                    steps_per_second = session_step_count / max(1, sport_duration)
                    stride_m = get_step_length_by_frequency(steps_per_second)
                    session_distance_km = (session_step_count * stride_m) / 1000
                avg_stride_m = round((session_distance_km * 1000) / session_step_count, 2)
            else:
                avg_stride_m = 0.0

            record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "mode": "运动",
                "duration": sport_duration,
                "pace": pace,
                "step": session_step_count,
                "carbon_reduce": session_carbon_reduce,
                "distance_km": round(session_distance_km, 3),
                "distance_step_km": round(step_distance_km, 3),
                "distance_gnss_km": round(gnss_distance_km, 3),
                "distance_source": distance_source,
                "avg_stride_m": avg_stride_m,
                "avg_cadence_spm": avg_cadence_spm,
                "series": [dict(point) for point in sport_series],
                "gnss_track": [dict(point) for point in sport_gnss_track],
                "gnss_valid_ratio": gnss_valid_ratio,
                "gnss_fix_samples": sport_gnss_fix_samples,
                "gnss_total_samples": sport_gnss_total_samples,
                "gnss_satellite_max": sport_gnss_satellite_max,
            }
            try:
                response = requests.post(f"{SERVER_URL}/api/sport_records",
                            json=record, timeout=5)
                if response.status_code == 200:
                    logger.info(f"运动记录已上传: {record}")
            except Exception as upload_err:
                logger.warning(f"运动记录上传失败: {upload_err}")
                # 上传失败，保存到本地pending_data
                offline_manager.append_pending_record(record)
                logger.info(f"运动记录已保存到本地: {record}")
        except Exception as e:
            logger.error(f"记录运动失败: {e}")
    sport_duration = 0
    sport_session_start_step = step_count
    sport_series = []
    sport_session_distance_km = 0.0
    _reset_sport_gnss_state()


def update_sitting_duration():
    """更新坐姿时长"""
    global sitting_start_time, sitting_duration

    if current_mode == MODE_LIFE and current_posture == "sitting":
        if sitting_start_time is None:
            sitting_start_time = time.time()
        else:
            sitting_duration = int(time.time() - sitting_start_time)
    else:
        sitting_start_time = None
        sitting_duration = 0


def update_activity_hours():
    """更新活动小时数"""
    global last_activity_hour, activity_hours

    current_hour = datetime.now().hour

    if current_posture == "standing":
        if current_hour != last_activity_hour:
            activity_hours.add(current_hour)
            last_activity_hour = current_hour


def reset_daily_stats():
    """每日重置统计数据"""
    global sport_time_today, activity_hours
    global step_count, carbon_reduce_count
    global step_pace_start_time, step_pace_last_step
    global step_pace_accumulated_distance, step_pace_accumulated_time
    global sport_pace_total_distance, sport_pace_total_time, sport_pace_start_time
    global current_pace_str, last_valid_pace_str, has_valid_pace
    global sport_session_start_step
    global sport_series, sport_series_last_ts, sport_series_last_step, sport_series_last_point_ts
    global sport_session_distance_km, sport_last_stride_m, sport_last_cadence_spm
    global sport_gnss_track, sport_gnss_last_point, sport_gnss_last_track_ts
    global sport_gnss_distance_km, sport_gnss_fix_samples, sport_gnss_total_samples
    global sport_gnss_satellite_max, sport_gnss_latest_point
    last_date = datetime.now().date()

    while running:
        time.sleep(60)
        current_date = datetime.now().date()
        if current_date != last_date:
            sport_time_today = 0
            activity_hours = set()
            step_count = 0
            carbon_reduce_count = 0
            sport_session_start_step = 0

            # 跨天后重置步数/配速相关计数，避免出现负增量或显示异常
            step_pace_start_time = None
            step_pace_last_step = 0
            step_pace_accumulated_distance = 0.0
            step_pace_accumulated_time = 0.0
            sport_pace_total_distance = 0.0
            sport_pace_total_time = 0.0
            sport_pace_start_time = None
            current_pace_str = "--'--\""
            last_valid_pace_str = "--'--\""
            has_valid_pace = False
            sport_series = []
            sport_series_last_ts = None
            sport_series_last_step = 0
            sport_series_last_point_ts = 0.0
            sport_session_distance_km = 0.0
            sport_last_stride_m = config.STEP_LENGTH_NORMAL
            sport_last_cadence_spm = 0.0
            sport_gnss_track = []
            sport_gnss_last_point = None
            sport_gnss_last_track_ts = 0.0
            sport_gnss_distance_km = 0.0
            sport_gnss_fix_samples = 0
            sport_gnss_total_samples = 0
            sport_gnss_satellite_max = 0
            sport_gnss_latest_point = None

            if step_detector:
                try:
                    step_detector.set_count(0)
                except Exception as e:
                    logger.warning(f"步数重置失败: {e}")

            last_date = current_date
            logger.info("已重置今日统计数据")


# ==================== 运动静止检测 ====================
def sport_idle_monitor():
    """运动模式静止监控"""
    global exit_sport_countdown, last_movement_time

    while running:
        time.sleep(1)

        if current_mode == MODE_SPORT and not emergency_mode:
            if last_movement_time is None:
                last_movement_time = time.time()

            idle_time = time.time() - last_movement_time

            if idle_time > 60 and not exit_sport_countdown:
                exit_sport_countdown = True
                stop_all_voice()
                add_voice("检测到您已静止一分钟，是否退出运动模式？请长按取消")

                countdown_start = time.time()
                while running and exit_sport_countdown:
                    if time.time() - countdown_start > 20:
                        if current_mode == MODE_SPORT:
                            change_mode_internal(MODE_LIFE)
                            add_voice("已自动退出运动模式")
                        exit_sport_countdown = False
                        break
                    time.sleep(0.5)
        last_movement_time = time.time()


# ==================== 会议模式 ====================
def enter_meeting_mode():
    """进入会议模式（完全黑屏）"""
    global meeting_black_rect

    logger.info("进入会议模式，显示黑屏")

    # 不再立即清除语音，让切换模式的语音能播放完

    # 隐藏所有UI元素
    hide_all_ui()

    # 显示会议模式黑色背景
    if 'meeting_black' in ui_elements:
        ui_elements['meeting_black'].config(state='normal')

    set_led_color(0, 0, 0)


def exit_meeting_mode():
    """退出会议模式"""

    logger.info("退出会议模式，恢复显示")

    # 重新初始化UI
    update_ui_mode()


# ==================== 模式处理 ====================
def handle_life_mode():
    """生活模式"""
    global last_temp, last_humi, led_position

    if message_showing:
        return

    try:
        if dht11:
            temp = round(dht11.temp_c() * 0.8, 1)
            humi = dht11.humidity()

            if temp is not None and humi is not None:
                # 更新温度数值
                if 'temp_text' in ui_elements:
                    ui_elements['temp_text'].config(text=f"{int(temp)}°C")
                # 更新湿度数值
                if 'humi_text' in ui_elements:
                    ui_elements['humi_text'].config(text=f"{int(humi)} %")

                # 温度变化播报
                if abs(temp - last_temp) > 5:
                    if temp > last_temp:
                        add_voice(f"温度上升，当前{int(temp)}度，请注意减衣")
                    else:
                        add_voice(f"温度下降，当前{int(temp)}度，请注意保暖")
                    last_temp = temp
                    last_humi = humi

                # LED控制
                if led_strip and knob:
                    color = update_led_by_temp_humi(temp, humi)
                    led_strip[led_position] = (0, 0, 0)
                    led_position += 1
                    if led_position == LED_COUNT:
                        led_position = 0
                    led_strip[led_position] = (color[0], color[1], color[2])
    except:
        pass

    # 姿态检测
    detect_posture()
    update_sitting_duration()

    # 更新坐姿时长
    sitting_min = sitting_duration // 60
    if 'sitting_text' in ui_elements:
        ui_elements['sitting_text'].config(text=f"{sitting_min}分钟")

    # 坐姿提醒播报
    if sitting_duration > 0 and sitting_duration >= sitting_remind_duration:
        if sitting_duration % sitting_remind_duration < 2:
            stop_all_voice()
            add_voice("您已经坐了很久，请站起来活动一下")

    # 更新环境状态显示（多状态用空格分开）
    env_status, _ = get_environment_status()
    # 用空格合并多个状态
    status_text = ' '.join(env_status)
    if 'env_status' in ui_elements:
        if env_status:
            ui_elements['env_status'].config(text=status_text)
        else:
            ui_elements['env_status'].config(text=status_text, x=175, y=115, origin='center')

    update_activity_hours()

    if detect_fall() and not fall_detected:
        trigger_fall_alarm()


def gnss_search_thread_func():
    """GNSS搜星线程（30秒搜星）"""
    global gnss_valid, gnss_searching, gnss_next_search_time
    global gnss_search_disabled_for_session, gnss_last_health_check_time

    if not GNSS_AVAILABLE:
        gnss_searching = False
        logger.warning("GNSS搜星线程未启动：驱动不可用")
        return

    if not gnss_manager.is_active:
        gnss_searching = False
        logger.warning("GNSS搜星线程未启动：GNSS尚未成功启动")
        return

    gnss_searching = True
    gnss_search_start = time.time()
    logger.info("开始30秒GNSS搜星...")

    while running and gnss_searching and current_mode == MODE_SPORT:
        sat_count = gnss_manager.get_satellite_count()
        gnss_valid = gnss_manager.has_valid_fix(sat_count)
        logger.debug(f"GNSS搜星中: {sat_count}颗")

        if gnss_valid:
            gnss_last_health_check_time = time.time()
            logger.info(f"GNSS搜星成功: {sat_count}颗")
            break

        if (time.time() - gnss_search_start) >= 30:
            gnss_valid = False
            gnss_search_disabled_for_session = True
            gnss_last_health_check_time = time.time()
            logger.info("GNSS搜星超时（30秒），本次运动模式不再重新搜星")
            add_voice("您当前可能处于室内，卫星信号弱，本次运动将不再尝试卫星搜星")
            break

        time.sleep(1)

    gnss_searching = False

def handle_sport_mode():
    """运动模式"""
    global fall_detected, emergency_mode, step_count, carbon_reduce_count, current_pace_str
    global gps_speed_read_time, gps_current_speed, step_pace_start_time, step_pace_last_step
    global gnss_searching, gnss_search_thread, gnss_next_search_time
    global gnss_initial_search_done, gnss_search_disabled_for_session, gnss_last_health_check_time
    global last_valid_pace_str, has_valid_pace
    global sport_pace_total_distance, sport_pace_total_time, sport_pace_start_time
    global gnss_last_check_time, gnss_valid

    if message_showing:
        return

    update_sport_time()

    # 启动GNSS（用于速度获取）
    gnss_started = gnss_manager.is_active
    if not gnss_started:
        gnss_started = gnss_manager.start()
        if gnss_started:
            gnss_last_check_time = None

    # 进入运动模式后只启动一次首次30秒搜星
    if gnss_started and not gnss_initial_search_done and not gnss_search_disabled_for_session and (gnss_search_thread is None or not gnss_search_thread.is_alive()):
        gnss_initial_search_done = True
        gnss_searching = True
        gnss_search_thread = threading.Thread(target=gnss_search_thread_func, daemon=True)
        gnss_search_thread.start()

    # 启动呼吸灯
    start_led_breathing()

    detect_movement()

    sat_count = 0
    gnss_sample_refreshed = False
    if GNSS_AVAILABLE:
        current_gnss_time = time.time()
        if gnss_last_check_time is None or (current_gnss_time - gnss_last_check_time) >= 1:
            sat_count = gnss_manager.get_satellite_count()
            gnss_valid = gnss_manager.has_valid_fix(sat_count)
            gnss_last_check_time = current_gnss_time
            gnss_sample_refreshed = True
        else:
            sat_count = gnss_manager.last_satellite_count
            gnss_valid = gnss_manager.has_valid_fix(sat_count)

        if gnss_sample_refreshed:
            _update_gnss_track(sat_count=sat_count, now=gnss_last_check_time)

        # 首次搜星成功后，运动模式下每5秒检查一次卫星数量，低于阈值则重新搜星
        if gnss_started and gnss_initial_search_done and not gnss_searching and not gnss_search_disabled_for_session:
            health_check_now = time.time()
            if gnss_last_health_check_time is None or (health_check_now - gnss_last_health_check_time) >= GNSS_HEALTH_CHECK_INTERVAL_SEC:
                gnss_last_health_check_time = health_check_now
                if not gnss_manager.is_fix_satellite_count(sat_count):
                    logger.info(f"GNSS卫星数不足（{sat_count}颗），重新开始30秒搜星")
                    gnss_searching = True
                    gnss_search_thread = threading.Thread(target=gnss_search_thread_func, daemon=True)
                    gnss_search_thread.start()

    if 'gps_status_text' in ui_elements:
        gps_text = gnss_manager.get_status_text(sat_count) if GNSS_AVAILABLE else "GPS:--"
        ui_elements['gps_status_text'].config(text=gps_text)

    # 读取加速度数据用于调试记录
    fall_detected_now = False
    try:
        ax, ay, az = read_acceleration()
        if ax is not None:
            import math
            acc_mag = math.sqrt(ax**2 + ay**2 + az**2)

            # 步数检测
            detected, step_record = detect_step()
            if detected:
                step_count = step_detector.get_step_count()
                carbon_reduce_count = step_count * config.CARBON_PER_STEP

            # 记录跌倒调试数据
            is_fall, fall_state = False, {}
            if fall_detector:
                is_fall, fall_state = fall_detector.check(ax, ay, az)
                fall_detected_now = is_fall
            pitch, roll = 0, 0
            if attitude_calculator:
                pitch, roll = attitude_calculator.update(ax, ay, az)
            debug_logger.log_fall(
                ax, ay, az, acc_mag, pitch, roll,
                fall_state.get('state', 'unknown') if fall_state else 'unknown',
                fall_state.get('variance', 0) if fall_state else 0,
                fall_state.get('peak_acc', 0) if fall_state else 0,
                fall_state.get('min_acc', 0) if fall_state else 0,
                fall_state.get('angle_change', 0) if fall_state else 0
            )
    except Exception as e:
        logger.error(f"运动模式数据记录错误: {e}")

    # === 配速计算（GNSS优先，步数备用）===
    current_time = time.time()

    # GNSS有效时，每5秒读取速度并按 m/s 直接换算配速
    if gnss_valid:
        if gps_speed_read_time is None:
            gps_speed_read_time = current_time

        elapsed = current_time - gps_speed_read_time
        if elapsed >= GNSS_PACE_INTERVAL_SEC:
            gps_current_speed = gnss_manager.get_speed()  # km/h
            gps_speed_read_time = current_time
            logger.debug(f"GNSS速度读取: {gps_current_speed} km/h")

            if gps_current_speed is not None and gps_current_speed > 0:
                speed_mps = gps_current_speed / 3.6
                pace = 1000 / (speed_mps * 60)  # 配速(分钟/公里)
                distance_km = (speed_mps * elapsed) / 1000.0

                if speed_mps > 0 and _is_valid_running_pace(pace):
                    minutes = int(pace)
                    seconds = int((pace - minutes) * 60)
                    current_pace_str = f"{minutes}'{seconds:02d}\""
                    last_valid_pace_str = current_pace_str
                    has_valid_pace = True
                    # 累计到平均配速计算
                    sport_pace_total_distance += distance_km
                    sport_pace_total_time += elapsed
                    if sport_pace_start_time is None:
                        sport_pace_start_time = current_time - elapsed
                    logger.debug(f"GNSS配速有效: {current_pace_str}")
                else:
                    # 配速无效，使用最近有效值或默认值
                    current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""
                    logger.debug(f"GNSS配速无效（超出有效范围 {PACE_VALID_MIN_MIN_PER_KM:.0f}'00\"~{PACE_VALID_MAX_MIN_PER_KM:.0f}'00\"）")
            else:
                # GNSS速度无效，使用最近有效值或默认值
                current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""
                logger.debug("GNSS速度无效")
    else:
        # GNSS无效，使用步数计算配速（每30秒）
        # 逻辑：若总步数为0，不计时；第一次步数增加时开始计时30s；30s内步数为0则停止

        if step_count == 0:
            # 总步数为0，不计时，显示默认值
            step_pace_start_time = None
            step_pace_last_step = step_count
            current_pace_str = "--'--\""
            logger.debug("步数配速: 步数为0，不计时")
        else:
            # 有步数的情况
            if step_pace_start_time is None:
                # 尚未开始计时，检查是否有步数增加
                if step_count > 0:
                    # 第一次出现步数，开始计时30s
                    step_pace_start_time = current_time
                    step_pace_last_step = step_count
                    logger.info(f"步数配速: 开始30s计时，步数={step_count}")
            else:
                # 已在计时中
                step_elapsed = current_time - step_pace_start_time
                steps_in_period = step_count - step_pace_last_step

                if step_elapsed >= 30:
                    # 30秒到，计算配速
                    if steps_in_period >= 10:
                        steps_per_second = steps_in_period / step_elapsed
                        step_length = get_step_length_by_frequency(steps_per_second)
                        distance_km = steps_in_period * step_length / 1000
                        duration_min = step_elapsed / 60
                        pace = duration_min / distance_km if distance_km > 0 else None

                        if _is_valid_running_pace(pace):
                            minutes = int(pace)
                            seconds = int((pace - minutes) * 60)
                            current_pace_str = f"{minutes}'{seconds:02d}\""
                            last_valid_pace_str = current_pace_str
                            has_valid_pace = True
                            # 累计到平均配速计算
                            sport_pace_total_distance += distance_km
                            sport_pace_total_time += step_elapsed
                            if sport_pace_start_time is None:
                                sport_pace_start_time = step_pace_start_time
                            logger.info(f"步数配速有效: {current_pace_str}")
                        else:
                            # 配速无效，使用最近有效值或默认值
                            current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""
                            logger.debug(f"步数配速无效（超出有效范围 {PACE_VALID_MIN_MIN_PER_KM:.0f}'00\"~{PACE_VALID_MAX_MIN_PER_KM:.0f}'00\"）")
                    else:
                        # 步数不足10步，使用最近有效值或默认值
                        current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""
                        logger.debug("步数配速无效（步数不足10步）")

                    # 重置计时
                    step_pace_start_time = current_time
                    step_pace_last_step = step_count
                    logger.debug(f"步数配速计算: {steps_in_period}步/{step_elapsed:.0f}秒 = {current_pace_str}")
                else:
                    # 30秒未到，检查是否有步数增加（停止条件：30s内步数为0）
                    if steps_in_period == 0:
                        # 30s内步数为0，停止计时，显示最近有效值
                        step_pace_start_time = None
                        step_pace_last_step = step_count
                        current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""
                        logger.info(f"步数配速: 30s内无步数增加，停止计算")
                    else:
                        # 仍在计时中，继续显示默认值或最近有效值
                        current_pace_str = last_valid_pace_str if has_valid_pace else "--'--\""

    _update_sport_series(current_time)

    # 显示配速
    if 'pace_text' in ui_elements:
        ui_elements['pace_text'].config(text=current_pace_str)

    # 更新步数
    if 'step_text' in ui_elements:
        ui_elements['step_text'].config(text=f"{step_count} 步")

    # 更新减碳量
    if 'carbon_reduce_text' in ui_elements:
        if carbon_reduce_count >= 1000:
            carbon_str = f"{int(carbon_reduce_count)}g"
        elif carbon_reduce_count >= 100:
            carbon_str = f"{round(carbon_reduce_count, 1)}g"
        elif carbon_reduce_count >= 1:
            carbon_str = f"{round(carbon_reduce_count, 2)}g"
        else:
            carbon_str = f"{round(carbon_reduce_count, 2)}g"
        ui_elements['carbon_reduce_text'].config(text=carbon_str)

    # 跌倒检测
    if fall_detected_now and not fall_detected:
        trigger_fall_alarm()


def handle_meeting_mode():
    """会议模式"""
    pass


def emergency_countdown():
    """紧急倒计时"""
    global emergency_mode, fall_detected, touch_press_start

    logger.info("紧急倒计时开始...")

    for i in range(20, 0, -1):
        if not running:
            break

        logger.info(f"紧急倒计时: {i}秒")
        time.sleep(1)

        if touch_press_start is not None:
            press_duration = time.time() - touch_press_start
            if press_duration >= long_press_threshold:
                fall_detected = False
                add_voice("紧急警报已取消")
                logger.info("紧急倒计时已取消")
                return

    emergency_mode = True
    logger.warning("紧急倒计时超时，进入紧急模式")
    handle_emergency()


def handle_emergency():
    """处理紧急情况（非阻塞LED）"""
    logger.warning("启动紧急求助")
    stop_all_voice()
    add_voice("紧急求助！紧急求助！需要帮助！")

    # 启动SOS闪烁（非阻塞）
    start_led_sos()

    while emergency_mode and running:
        add_voice("需要帮助")
        time.sleep(2)  # 语音间隔，不阻塞LED


# ==================== 触摸板处理 ====================
last_touch_state = 0
touch_press_start = None


def touch_monitor():
    """触摸板监控线程"""
    global current_mode, touch_press_start, fall_detected, emergency_mode
    global exit_sport_countdown, last_touch_state, message_showing
    global last_click_time, long_press_2s_voiced, env_auto_exit_start_time, double_click_last_time
    global env_exit_cancelled_by_touch

    # 长按触发标志，避免重复触发
    long_press_triggered = False

    while running:
        try:
            if touch:
                current_state = touch.value()
            else:
                time.sleep(0.05)
                continue

            # 按下
            if current_state == 1 and last_touch_state == 0:
                touch_press_start = time.time()
                long_press_triggered = False
                long_press_2s_voiced = False  # 重置2秒语音标志
                # 取消环境自动退出倒计时，并标记被触摸板取消
                if env_auto_exit_start_time is not None:
                    env_exit_cancelled_by_touch = True
                    add_voice("已取消自动退出，将保持在运动模式")
                env_auto_exit_start_time = None

            # 触摸板保持按下状态 - 检测长按
            elif current_state == 1 and last_touch_state == 1:
                if touch_press_start is not None:
                    press_duration = time.time() - touch_press_start

                    # 运动模式：连续长按4秒，中途2秒语音提示
                    # 如果存在环境恶劣退出计时、已被触摸板取消、或存在紧急倒计时，则忽略运动模式的长按退出
                    if current_mode == MODE_SPORT and not long_press_triggered and env_auto_exit_start_time is None and not env_exit_cancelled_by_touch and not emergency_mode:
                        # 达到2秒：播报语音提示
                        if press_duration >= 2.0 and not long_press_2s_voiced:
                            long_press_2s_voiced = True
                            stop_all_voice()
                            add_voice("即将退出运动模式，继续长按2秒后退出")
                            logger.info("运动模式：长按2秒，语音提示已播报")

                        # 达到4秒：确认退出（语音补偿2秒）
                        if press_duration >= 6.0:
                            long_press_triggered = True
                            old_mode = current_mode
                            change_mode_internal(MODE_LIFE)
                            logger.info(f"模式切换: {MODE_NAMES[old_mode]} → {MODE_NAMES[current_mode]}")
                            touch_press_start = None

                    # 其他情况：使用原来的2秒阈值
                    # 如果环境退出已被触摸板取消，则忽略
                    elif not long_press_triggered and press_duration >= long_press_threshold and not env_exit_cancelled_by_touch:
                        long_press_triggered = True

                        # 紧急模式取消
                        if fall_detected or emergency_mode:
                            fall_detected = False
                            emergency_mode = False
                            stop_led_breathing()  # 停止SOS灯
                            add_voice("紧急模式已取消")
                            logger.info("触摸板长按取消紧急模式")
                            stop_all_voice()
                            touch_press_start = None

                        # 消息显示中
                        elif message_showing:
                            exit_message_scroll()
                            logger.info("触摸板长按退出消息显示")
                            touch_press_start = None

                        # 生活/会议模式：使用config中的MODE_CYCLE切换
                        else:
                            old_mode = current_mode
                            # 找到当前模式在MODE_CYCLE中的索引
                            try:
                                current_idx = config.MODE_CYCLE.index(current_mode)
                                next_idx = (current_idx + 1) % len(config.MODE_CYCLE)
                                new_mode = config.MODE_CYCLE[next_idx]
                            except ValueError:
                                # 如果当前模式不在列表中，默认切换到下一个
                                new_mode = config.MODE_CYCLE[1] if current_mode == config.MODE_CYCLE[0] else config.MODE_CYCLE[0]

                            # 使用change_mode_internal处理模式切换（会播报语音）
                            change_mode_internal(new_mode)
                            logger.info(f"模式切换: {MODE_NAMES[old_mode]} → {MODE_NAMES[current_mode]}")
                            touch_press_start = None

            # 释放
            elif current_state == 0 and last_touch_state == 1:
                # 重置环境退出取消标志
                env_exit_cancelled_by_touch = False

                if touch_press_start is not None:
                    press_duration = time.time() - touch_press_start
                    current_time = time.time()

                    # 如果之前没有触发长按，作为短按处理
                    if not long_press_triggered and press_duration < long_press_threshold:
                        # 紧急模式/消息显示中：无效
                        if fall_detected or emergency_mode or message_showing:
                            pass
                        else:
                            # 双击检测（带冷却时间）
                            if current_time - double_click_last_time < double_click_cooldown:
                                # 在冷却时间内，作为新的单击
                                last_click_time = current_time
                            elif last_click_time is not None:
                                click_interval = current_time - last_click_time
                                if click_interval <= double_click_interval:
                                    # 双击触发播报
                                    if current_mode == MODE_LIFE:
                                        report_life_mode_status()
                                    elif current_mode == MODE_SPORT:
                                        report_sport_mode_status()
                                    double_click_last_time = current_time  # 更新冷却时间
                                    last_click_time = None  # 重置，避免三次点击触发多次
                                else:
                                    # 超过间隔，作为新的单击
                                    last_click_time = current_time
                            else:
                                # 第一次点击
                                last_click_time = current_time


                    touch_press_start = None

            last_touch_state = current_state

        except Exception as e:
            logger.error(f"触摸板监控错误: {e}")

        time.sleep(0.05)


# ==================== 旋钮处理 ====================
def knob_thread():
    """旋钮控制线程"""
    global led_brightness

    while running:
        if current_mode != MODE_MEETING:
            try:
                if knob and led_strip:
                    knob_value = knob.read_analog()
                    led_brightness = int(knob_value * 255 / 4095)
                    led_strip.brightness(led_brightness)
            except:
                pass
        time.sleep(0.1)


# ==================== 离线数据管理器 ====================
offline_manager = OfflineManager(SERVER_URL)


# ==================== HTTP通信 ====================
def send_status():
    """发送状态到服务器（带禁用重试机制）"""
    global sitting_remind_duration

    # 创建禁用重试的session（与try_connect一致）
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        session = requests.Session()
        retry = Retry(total=0, connect=0, read=0, redirect=0)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
    except:
        session = requests

    # 最多重试1次
    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            data = {
                "mode": current_mode,
                "temperature": last_temp,
                "humidity": last_humi,
                "brightness": led_brightness,
                "posture": current_posture,
                "pace": 0,
                "pace_str": current_pace_str if current_mode == MODE_SPORT else "--'--\"",
                "step": step_count,
                "carbon_reduce": carbon_reduce_count,
                "emergency": emergency_mode,
                "sport_time_today": sport_time_today,
                "activity_hours": list(activity_hours),
                "sitting_duration": sitting_duration,
                "sport_duration": sport_duration,
                "message_showing": message_showing,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            if session == requests:
                response = requests.post(
                    f"{SERVER_URL}/api/status",
                    json=data,
                    timeout=5
                )
            else:
                response = session.post(
                    f"{SERVER_URL}/api/status",
                    json=data,
                    timeout=5
                )

            if response.status_code == 200:
                result = response.json()
                commands = result.get("commands", [])
                sitting_remind_duration = result.get("sitting_remind_duration", 3600)
                for cmd in commands:
                    handle_command(cmd)
                return True
            else:
                if attempt < max_retries:
                    continue  # 重试
                logger.warning(f"发送状态失败: {response.status_code}")
                return False

        except Exception:
            # 静默处理连接错误，离线状态会通过 set_online_status 显示
            if attempt < max_retries:
                continue  # 重试
            return False

    return False


def change_mode_internal(new_mode):
    """内部模式切换"""
    global current_mode, current_pace_str
    global gps_speed_read_time, gps_current_speed, step_pace_start_time, step_pace_last_step
    global gnss_searching, gnss_last_check_time, gnss_valid, gnss_next_search_time
    global gnss_initial_search_done, gnss_search_disabled_for_session, gnss_last_health_check_time
    global last_valid_pace_str, has_valid_pace
    global sport_pace_total_distance, sport_pace_total_time, sport_pace_start_time
    global step_pace_accumulated_distance, step_pace_accumulated_time, sport_session_start_step

    if message_showing:
        return

    if not is_valid_mode(new_mode):
        logger.warning(f"忽略非法模式切换请求: {new_mode}")
        return

    old_mode = current_mode

    if old_mode == MODE_SPORT and new_mode != MODE_SPORT:
        if sport_duration > 30:
            record_sport_session()
        # 重置配速显示和计时器
        current_pace_str = "--'--\""
        last_valid_pace_str = "--'--\""
        has_valid_pace = False
        sport_pace_total_distance = 0.0
        sport_pace_total_time = 0.0
        sport_pace_start_time = None
        gps_speed_read_time = None
        gps_current_speed = None
        step_pace_start_time = None
        step_pace_last_step = 0
        step_pace_accumulated_distance = 0.0
        step_pace_accumulated_time = 0.0
        # 停止搜星
        gnss_searching = False
        gnss_last_check_time = None
        gnss_valid = False
        gnss_next_search_time = 0.0
        gnss_initial_search_done = False
        gnss_search_disabled_for_session = False
        gnss_last_health_check_time = None
        # 停止GNSS和呼吸灯
        gnss_manager.stop()
        stop_led_breathing()

    if old_mode == MODE_MEETING:
        exit_meeting_mode()

    current_mode = new_mode

    # 先清空语音队列
    stop_all_voice()
    time.sleep(0.1)

    # 切换到新模式后再播报语音
    logger.debug(f"[模式切换] 准备切换到新模式: {new_mode}, MODE_NAMES={MODE_NAMES[current_mode]}")
    add_voice(f"切换到{MODE_NAMES[current_mode]}", force=(current_mode == MODE_MEETING))
    logger.debug(f"[模式切换] add_voice已调用, voice_queue={voice_queue}")

    if current_mode == MODE_MEETING:
        logger.debug(f"[模式切换] 进入会议模式，准备等待1.5秒")
        time.sleep(1.5)  # 等待语音播放完再进入会议模式
        enter_meeting_mode()
        logger.debug(f"[模式切换] enter_meeting_mode已调用")
    elif current_mode == MODE_SPORT:
        gnss_next_search_time = 0.0
        gnss_initial_search_done = False
        gnss_search_disabled_for_session = False
        gnss_last_health_check_time = None
        time.sleep(0.5)
        update_ui_mode()
        # 运动模式环境检查
        _check_and_handle_sport_environment()
    else:
        time.sleep(0.5)
        update_ui_mode()


def handle_command(cmd):
    """处理服务器命令"""
    global current_mode, led_brightness

    command = cmd.get("command")

    if command == "change_mode":
        if message_showing:
            exit_message_scroll()

        new_mode = cmd.get("mode", current_mode)
        if is_valid_mode(new_mode):
            change_mode_internal(new_mode)

    elif command == "message":
        content = cmd.get("content", "")
        if content and current_mode != MODE_MEETING:
            show_message_scroll(content)

    elif command == "exit_message":
        if message_showing:
            exit_message_scroll()

    elif command == "set_brightness":
        led_brightness = cmd.get("value", led_brightness)


def communication_thread():
    """通信线程"""
    offline_check_interval = 5  # 离线模式下每5秒检查一次
    last_offline_check = 0

    while running:
        try:
            # 如果当前离线，每5秒尝试连接
            if not offline_manager.is_online:
                current_time = time.time()
                if current_time - last_offline_check >= offline_check_interval:
                    last_offline_check = current_time
                    # 尝试连接
                    if offline_manager.try_connect():
                        # 连接成功，切换到在线模式
                        offline_manager.set_online_status(True)
                        # 一次性同步所有pending数据
                        offline_manager.sync_all_pending()
                        logger.info("离线模式：连接成功，已同步数据")
                    else:
                        # 连接失败，保持离线
                        # 保存数据到本地
                        offline_manager.update_cache({
                            "step": step_count,
                            "carbon_reduce": carbon_reduce_count,
                            "sport_time_today": sport_time_today
                        })
                        time.sleep(UPDATE_INTERVAL)
                        continue

            # 在线模式：发送状态
            success = send_status()
            offline_manager.set_online_status(success)

            if success:
                # 成功后也尝试同步pending数据（可能有之前离线时的数据）
                offline_manager.sync_all_pending()
            else:
                # 发送失败，保存数据到本地
                offline_manager.update_cache({
                    "step": step_count,
                    "carbon_reduce": carbon_reduce_count,
                    "sport_time_today": sport_time_today
                })

        except Exception:
            # 静默处理连接错误，离线状态会通过 set_online_status 显示
            offline_manager.set_online_status(False)

        time.sleep(UPDATE_INTERVAL)


# ==================== GNSS速度管理器 ====================
gnss_manager = GNSSManager(getattr(config, 'GNSS_CONFIG', None))


# 主循环采样统计计数器
_sample_stats_counter = 0
_gnss_check_counter = 0  # GNSS检查计数器（每0.1秒递增，200次=20秒）


# ==================== 主循环 ====================
def main_loop():
    """主循环"""
    global _sample_stats_counter, _gnss_check_counter, gnss_valid

    while running:
        try:
            # 非运动模式（除会议模式外）每20秒检查一次GNSS卫星数量
            if current_mode != MODE_SPORT and current_mode != MODE_MEETING:
                _gnss_check_counter += 1
                if _gnss_check_counter >= 200:  # 0.1s * 200 = 20秒
                    _gnss_check_counter = 0
                    if GNSS_AVAILABLE:
                        sat_count = gnss_manager.get_satellite_count()
                        gnss_valid = gnss_manager.has_valid_fix(sat_count)
                        logger.debug(f"GNSS卫星检查: {sat_count}颗, 有效: {gnss_valid}")

            # 会议模式不显示任何内容
            if not message_showing:
                if current_mode != MODE_MEETING and gui:
                    # 更新时间（优先使用GNSS时间）
                    if 'time_text' in ui_elements:
                        if gnss_valid:
                            gnss_dt = gnss_manager.get_datetime()
                            if gnss_dt:
                                time_str = gnss_dt.strftime('%H:%M:%S')
                            else:
                                time_str = datetime.now().strftime('%H:%M:%S')
                        else:
                            time_str = datetime.now().strftime('%H:%M:%S')
                        ui_elements['time_text'].config(text=time_str)

            # 每5秒输出一次采样统计
            _sample_stats_counter += 1
            if _sample_stats_counter >= 50:  # 0.1s * 50 = 5秒
                _sample_stats_counter = 0
                if sampler is not None:
                    try:
                        from sensors import get_sampling_stats
                        stats = get_sampling_stats()
                        logger.debug(f"采样统计: 实际采样率 {stats['actual_sample_rate']:.1f}Hz"
                              f", 总采样: {stats['sample_count']}")
                    except Exception:
                        pass

            # 检查环境自动退出倒计时
            global env_auto_exit_start_time
            if env_auto_exit_start_time is not None:
                elapsed = time.time() - env_auto_exit_start_time
                if elapsed >= 15:
                    # 15秒后自动退出
                    env_auto_exit_start_time = None
                    if current_mode == MODE_SPORT:
                        change_mode_internal(MODE_LIFE)
                        add_voice("已自动退出运动模式")

            if not emergency_mode:
                if current_mode == MODE_LIFE:
                    handle_life_mode()
                elif current_mode == MODE_SPORT:
                    handle_sport_mode()
                elif current_mode == MODE_MEETING:
                    handle_meeting_mode()

        except Exception as e:
            logger.error(f"主循环错误: {e}")

        time.sleep(0.1)


# ==================== 启动程序 ====================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("运动腰带系统启动")
    logger.info("=" * 60)

    debug_logger.start()

    # 硬件初始化
    logger.info("初始化硬件...")

    if HARDWARE_AVAILABLE:
        Board().begin()

        dht11 = DHT11(Pin(PIN_DHT11))
        logger.info("DHT11初始化成功")
        touch = Pin(PIN_TOUCH, Pin.IN)
        logger.info("触摸板初始化成功")
        knob = Pin(PIN_KNOB, Pin.ANALOG)
        logger.info("旋钮初始化成功")
        led_strip = NeoPixel(Pin(PIN_LED), LED_COUNT)
        led_strip.brightness(led_brightness)
        logger.info("LED初始化成功")

        tts = DFRobot_SpeechSynthesis_I2C()
        tts.begin(tts.V2)
        tts.set_voice(9)
        tts.set_speed(8)
        tts.set_tone(5)
        tts.set_sound_type(tts.FEMALE2)

        gui = GUI()
    else:
        logger.warning("运行在模拟模式")

    init_ui()

    restore_today_stats_from_server()

    logger.info("硬件初始化完成")
    logger.info(f"sensors模块: {'已加载' if sensors_module_available else '未加载'}")
    logger.info(f"utils模块: {'已加载' if utils_available else '未加载'}")
    logger.info("=" * 60)

    try:
        threads = [
            threading.Thread(target=voice_thread, daemon=True, name="voice"),
            threading.Thread(target=knob_thread, daemon=True, name="knob"),
            threading.Thread(target=touch_monitor, daemon=True, name="touch"),
            threading.Thread(target=main_loop, daemon=True, name="main"),
            threading.Thread(target=communication_thread, daemon=True, name="comm"),
            threading.Thread(target=reset_daily_stats, daemon=True, name="reset"),
            threading.Thread(target=sport_idle_monitor, daemon=True, name="idle")
        ]

        for t in threads:
            t.start()
            logger.info(f"启动线程: {t.name}")

        logger.info("=" * 60)
        logger.info("系统启动完成")
        logger.info(f"服务器: {SERVER_URL}")
        logger.info("=" * 60)

        add_voice("运动腰带系统已启动")

        while running:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("程序中断")
    finally:
        exit_handler()
