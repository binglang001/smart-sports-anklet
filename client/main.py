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
import os
import json
import requests
from datetime import datetime, timedelta

# 导入日志模块
from utils.logger import get_logger
logger = get_logger('main')

# ==================== 传感器模块（核心算法）====================
# 优先使用sensors模块的修复版本
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
    logger.warning(f"sensors模块不可用: {e}")

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


# ==================== GNSS模块 ====================
GNSS_AVAILABLE = False
try:
    import sys
    sys.path.append("/root/mindplus/.lib/thirdExtension/liliang-gravitygnss-thirdex")
    from DFRobot_GNSS import *
    GNSS_AVAILABLE = True
except ImportError:
    logger.warning("GNSS模块不可用")


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
PIN_BUTTON = _to_pin(config.PIN_BUTTON)
PIN_KNOB = _to_pin(config.PIN_KNOB)
PIN_LED = _to_pin(config.PIN_LED)
LED_COUNT = config.LED_COUNT

# 模式定义
MODE_LIFE = config.MODE_LIFE
MODE_SPORT = config.MODE_SPORT
MODE_MEETING = config.MODE_MEETING
MODE_NAMES = ["生活模式", "运动模式", "会议模式"]
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
button_press_start = None
long_press_threshold = 2.0  # 长按阈值改为2秒
double_click_interval = 0.7  # 双击最大间隔
last_click_time = None  # 上次点击时间
long_press_2s_voiced = False  # 长按2秒语音是否已播报
sitting_remind_duration = config.DEFAULT_SITTING_REMIND_DURATION
step_count = 0
carbon_reduce_count = 0

# 配速显示
current_pace_str = "--'--\""  # 当前配速显示

# GPS速度读取计时器（30秒）
gps_speed_read_time = None  # 上次读取GPS速度的时间
gps_current_speed = None  # 当前GPS速度(km/h)

# 步数配速计算计时器
step_pace_start_time = None  # 步数配速计算开始时间
step_pace_last_step = 0  # 上次记录的步数

# UI元素
ui_elements = {}
message_showing = False
current_message = ""
message_scroll_thread = None
meeting_black_rect = None

# 步数记录
last_sent_step = 0
led_position = 0


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
button = None
knob = None
led_strip = None
tts = None
gui = None


# ==================== UI初始化 ====================
def init_ui():
    """初始化UI"""
    global ui_elements

    if not gui:
        return

    # 清空旧UI
    gui.clear()
    ui_elements = {}

    # 绘制背景图片（根据当前模式）
    if current_mode == MODE_LIFE:
        ui_elements['background'] = gui.draw_image(image="ui/life_mode.png", x=0, y=0)
    elif current_mode == MODE_SPORT:
        ui_elements['background'] = gui.draw_image(image="ui/sport_mode.png", x=0, y=0)
    # 会议模式不画背景（全黑）

    # 时间（所有模式，angle=90表示横放）
    ui_elements['time_text'] = gui.draw_text(
        text="00:00:00",
        x=0, y=320,
        font_size=25, color="#000000", angle=90
    )

    if current_mode == MODE_LIFE:
        # 温度
        ui_elements['temp_text'] = gui.draw_text(
            text="--°C",
            x=178, y=223,
            font_size=11, color="#F17D30", angle=90, origin='center'
        )
        # 湿度
        ui_elements['humi_text'] = gui.draw_text(
            text="-- %",
            x=201, y=221,
            font_size=11, color="#5A84F2", angle=90, origin='center'
        )
        # 坐姿时长
        ui_elements['sitting_text'] = gui.draw_text(
            text="0分钟",
            x=213, y=217,
            font_size=11, color="#000000", angle=90
        )
        # 环境状态（默认适宜）
        ui_elements['env_status'] = gui.draw_text(
            text="适宜",
            x=163, y=139,
            font_size=18, color="#808080", angle=90
        )

    elif current_mode == MODE_SPORT:
        # 步数
        ui_elements['step_text'] = gui.draw_text(
            text="0 步",
            x=197, y=280,
            font_size=11, color="#000000", angle=90, origin='center'
        )
        # 配速
        ui_elements['pace_text'] = gui.draw_text(
            text="--'--\"",
            x=220, y=245,
            font_size=11, color="#000000", angle=90
        )
        # 减碳量
        ui_elements['carbon_reduce_text'] = gui.draw_text(
            text="0.00g",
            x=181, y=95,
            font_size=18, color="#8AD70D", angle=90, origin='center'
        )


def update_ui_mode():
    """根据模式更新UI显示"""
    global ui_elements

    if message_showing:
        return

    # 清空当前所有UI元素
    for key in list(ui_elements.keys()):
        try:
            ui_elements[key].remove()
        except:
            pass

    # 重新绘制背景和UI
    if current_mode == MODE_LIFE:
        # 背景
        ui_elements['background'] = gui.draw_image(image="ui/life_mode.png", x=0, y=0)

        # 时间
        now_str = datetime.now().strftime('%H:%M:%S')
        ui_elements['time_text'] = gui.draw_text(
            text=now_str,
            x=0, y=320,
            font_size=25, color="#000000", angle=90
        )

        # 温度
        ui_elements['temp_text'] = gui.draw_text(
            text="--°C",
            x=178, y=223,
            font_size=11, color="#F17D30", angle=90, origin='center'
        )

        # 湿度
        ui_elements['humi_text'] = gui.draw_text(
            text="-- %",
            x=201, y=223,
            font_size=11, color="#5A84F2", angle=90, origin='center'
        )

        # 坐姿时长
        ui_elements['sitting_text'] = gui.draw_text(
            text="0分钟",
            x=213, y=217,
            font_size=11, color="#000000", angle=90
        )

        # 环境状态（支持两个状态显示）
        ui_elements['env_status'] = gui.draw_text(
            text="适宜",
            x=163, y=139,
            font_size=18, color="#808080", angle=90
        )
        ui_elements['env_status_2'] = gui.draw_text(
            text="",
            x=163, y=165,
            font_size=18, color="#808080", angle=90
        )

    elif current_mode == MODE_SPORT:
        # 背景
        ui_elements['background'] = gui.draw_image(image="ui/sport_mode.png", x=0, y=0)

        # 时间
        now_str = datetime.now().strftime('%H:%M:%S')
        ui_elements['time_text'] = gui.draw_text(
            text=now_str,
            x=0, y=320,
            font_size=25, color="#000000", angle=90
        )

        # 步数
        ui_elements['step_text'] = gui.draw_text(
            text="0 步",
            x=197, y=280,
            font_size=11, color="#000000", angle=90, origin='center'
        )

        # 配速
        ui_elements['pace_text'] = gui.draw_text(
            text="--'--\"",
            x=220, y=245,
            font_size=11, color="#000000", angle=90
        )

        # 减碳量
        ui_elements['carbon_reduce_text'] = gui.draw_text(
            text="0.00g",
            x=181, y=95,
            font_size=18, color="#8AD70D", angle=90, origin='center'
        )

    elif current_mode == MODE_MEETING:
        # 会议模式完全黑屏
        gui.clear()


# ==================== 环境状态判断 ====================
def get_environment_status():
    """获取环境状态，返回(状态列表, 语音播报文本)"""
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
        need_temp_tip = False
        need_humi_tip = False

        if "寒冷" in temp_status or "偏冷" in temp_status:
            need_temp_tip = True
        elif "炎热" in temp_status or "偏热" in temp_status:
            need_temp_tip = True

        if "干燥" in humi_status:
            need_humi_tip = True
        elif "闷热" in humi_status or "潮湿" in humi_status:
            need_humi_tip = True

        # 播报温度
        if need_temp_tip:
            if "寒冷" in temp_status or "偏冷" in temp_status:
                voice_text += f"当前温度{int(temp)}度，请注意保暖。"
            else:
                voice_text += f"当前温度{int(temp)}度，请注意降温。"

        # 播报湿度
        if need_humi_tip:
            if "干燥" in humi_status:
                voice_text += f"当前湿度{int(humi)}%，请注意补水。"
            else:
                voice_text += f"当前湿度{int(humi)}%，请注意防潮。"

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
    time_str = f"{now.hour}时{now.minute}分{now.second}秒"
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
    global message_showing, current_message, message_scroll_thread

    stop_all_voice()

    if message_scroll_thread and message_scroll_thread.is_alive():
        message_showing = False
        time.sleep(0.3)

    current_message = message

    for key in ui_elements:
        try:
            ui_elements[key].config(state='hidden')
        except:
            pass

    time.sleep(0.1)
    message_showing = True
    add_voice(message)

    message_scroll_thread = threading.Thread(target=scroll_message_thread,
                                            args=(message,), daemon=True)
    message_scroll_thread.start()


def scroll_message_thread(message):
    """滚动消息线程"""
    global message_showing, current_message

    time.sleep(0.1)

    punctuation = ['，', '。', '、', '！', '？', '；', '：', '…', ',', '.', '!', '?', ';', ':', '\'', '"', '"', '"', ''', ''']
    processed_chars = []
    temp_char = ""

    for char in message:
        if char in punctuation:
            temp_char += char
        else:
            if temp_char:
                processed_chars.append(temp_char)
            temp_char = char

    if temp_char:
        processed_chars.append(temp_char)

    vertical_message = '\n'.join(processed_chars)
    text_color = "#FF0000" if emergency_mode else "#000000"
    font_size = 140

    if not gui:
        return

    white_bg = gui.fill_rect(x=0, y=0, w=240, h=320, color="#FFFFFF")

    if "," in vertical_message or "，" in vertical_message:
        scroll_text = gui.draw_text(x=200, y=320, text=vertical_message,
                                color=text_color, font_size=font_size, anchor="n")
    else:
        scroll_text = gui.draw_text(x=120, y=320, text=vertical_message,
                                    color=text_color, font_size=font_size, anchor="n")

    scroll_speed = 80
    frame_time = 0.033

    start_time = time.perf_counter()
    screen_height = 320
    line_height = int(font_size * 1.2)
    text_height = len(processed_chars) * line_height
    total_scroll_distance = text_height + screen_height
    total_scroll_time = total_scroll_distance / scroll_speed

    while message_showing and running and current_message == message:
        elapsed = time.perf_counter() - start_time
        scroll_progress = (elapsed % total_scroll_time) / total_scroll_time
        y_pos = screen_height - int(scroll_progress * total_scroll_distance)

        try:
            scroll_text.config(y=y_pos)
        except:
            break

        time.sleep(frame_time)

    try:
        scroll_text.remove()
        white_bg.remove()
    except:
        pass


def exit_message_scroll():
    """退出消息滚动"""
    global message_showing, current_message

    message_showing = False
    current_message = ""
    stop_all_voice()

    time.sleep(0.5)

    if gui:
        gui.clear()
        update_ui_mode()

        if current_mode == MODE_MEETING:
            enter_meeting_mode()


# ==================== 语音合成 ====================
def add_voice(text):
    """添加语音到队列"""
    if voice_enabled and current_mode != MODE_MEETING:
        voice_queue.append(text)
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
        if voice_queue and voice_enabled and current_mode != MODE_MEETING:
            text = voice_queue.pop(0)
            try:
                if tts:
                    tts.speak(text)
                    time.sleep(0.5)
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
    steps = 10  # 减少步数让闪烁更快
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
    fade_duration = 0.2

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
                        # 传入None让step_detector不做额外重力去除，直接使用linear值
                        detected, step_record = step_detector.add_sample(linear_x, linear_y, linear_z, None, None, None)

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


def update_sport_time():
    """更新运动时长"""
    global sport_start_time, sport_time_today, sport_duration, last_update_time

    if current_mode == MODE_SPORT:
        if sport_start_time is None:
            sport_start_time = time.time()
            last_update_time = time.time()
            sport_duration = 0
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
    global sport_duration

    if sport_duration > 30:
        try:
            pace = calculate_pace()
            # calculate_step_and_carbon returns dict but we use global step_count/carbon_reduce_count
            calculate_step_and_carbon()
            record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "mode": "运动" if current_mode == MODE_SPORT else "会议",
                "duration": sport_duration,
                "pace": pace,
                "step": step_count,
                "carbon_reduce": carbon_reduce_count
            }
            try:
                response = requests.post(f"{SERVER_URL}/api/sport_records",
                            json=record, timeout=5)
                if response.status_code == 200:
                    logger.info(f"运动记录已上传: {record}")
            except Exception as upload_err:
                logger.warning(f"运动记录上传失败: {upload_err}")
        except Exception as e:
            logger.error(f"记录运动失败: {e}")
    sport_duration = 0


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
    last_date = datetime.now().date()

    while running:
        time.sleep(60)
        current_date = datetime.now().date()
        if current_date != last_date:
            sport_time_today = 0
            activity_hours = set()
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
                add_voice("检测到您已静止一分钟，是否退出运动模式？请长按按钮取消")

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

    # 清空所有UI元素
    for key in list(ui_elements.keys()):
        try:
            ui_elements[key].remove()
        except:
            pass

    # 直接清空就是黑色
    if gui:
        gui.clear()

    set_led_color(0, 0, 0)


def exit_meeting_mode():
    """退出会议模式"""
    global meeting_black_rect

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
            add_voice("您已经坐了很久，请站起来活动一下")

    # 更新环境状态显示（支持两个状态）
    env_status, _ = get_environment_status()
    if 'env_status' in ui_elements:
        if env_status:
            # 多个状态时分散显示
            if len(env_status) == 1:
                ui_elements['env_status'].config(text=env_status[0], x=163, y=139)
                if 'env_status_2' in ui_elements:
                    ui_elements['env_status_2'].config(text="")
            else:
                # 第一个状态在上方，第二个状态在下方
                ui_elements['env_status'].config(text=env_status[0], x=163, y=139)
                if 'env_status_2' in ui_elements:
                    ui_elements['env_status_2'].config(text=env_status[1], x=163, y=165)
        else:
            ui_elements['env_status'].config(text="适宜", x=163, y=139)
            if 'env_status_2' in ui_elements:
                ui_elements['env_status_2'].config(text="")

    update_activity_hours()


def handle_sport_mode():
    """运动模式"""
    global fall_detected, emergency_mode, step_count, carbon_reduce_count, current_pace_str
    global gps_speed_read_time, gps_current_speed, step_pace_start_time, step_pace_last_step

    if message_showing:
        return

    # 启动GNSS（用于速度获取）
    if not gnss_manager.is_active:
        gnss_manager.start()

    # 启动呼吸灯
    start_led_breathing()

    detect_movement()

    # 读取加速度数据用于调试记录
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

    # === 配速计算（GPS优先，步数备用）===
    current_time = time.time()

    # 尝试读取GPS速度（每30秒）
    if gps_speed_read_time is None:
        gps_speed_read_time = current_time

    elapsed = current_time - gps_speed_read_time
    if elapsed >= 30:
        gps_current_speed = gnss_manager.get_speed()  # km/h
        gps_speed_read_time = current_time
        logger.info(f"GPS速度读取: {gps_current_speed} km/h")

    # 使用GPS速度计算配速
    if gps_current_speed is not None and gps_current_speed > 0:
        pace = 60 / gps_current_speed
        if 3 <= pace <= 30:
            minutes = int(pace)
            seconds = int((pace - minutes) * 60)
            current_pace_str = f"{minutes}'{seconds:02d}\""
        else:
            current_pace_str = "--'--\""
    else:
        # GPS无效，使用步数计算配速（每30秒）
        if step_pace_start_time is None:
            step_pace_start_time = current_time
            step_pace_last_step = step_count

        step_elapsed = current_time - step_pace_start_time
        if step_elapsed >= 30:
            steps_in_30s = step_count - step_pace_last_step
            if steps_in_30s >= 10:
                # 计算步频（步/秒）
                steps_per_second = steps_in_30s / step_elapsed
                # 根据步频获取对应的步长
                step_length = get_step_length_by_frequency(steps_per_second)
                distance_km = steps_in_30s * step_length / 1000
                duration_min = step_elapsed / 60
                if distance_km > 0.01 and duration_min > 0:
                    pace = duration_min / distance_km
                    if 3 <= pace <= 30:
                        minutes = int(pace)
                        seconds = int((pace - minutes) * 60)
                        current_pace_str = f"{minutes}'{seconds:02d}\""
                    else:
                        current_pace_str = "--'--\""
                else:
                    current_pace_str = "--'--\""
            else:
                current_pace_str = "--'--\""
            # 重置计时
            step_pace_start_time = current_time
            step_pace_last_step = step_count
            logger.info(f"步数配速计算: {steps_in_30s}步/{step_elapsed:.0f}秒 = {current_pace_str}")

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
            carbon_str = f"{int(carbon_reduce_count * 1000)}g"
        ui_elements['carbon_reduce_text'].config(text=carbon_str)

    # 跌倒检测
    if detect_fall() and not fall_detected:
        logger.warning("检测到摔倒！")
        fall_detected = True
        add_voice("检测到摔倒，是否需要帮助？长按按钮取消警报")
        threading.Thread(target=emergency_countdown, daemon=True).start()

    update_sport_time()


def handle_meeting_mode():
    """会议模式"""
    pass


def emergency_countdown():
    """紧急倒计时"""
    global emergency_mode, fall_detected, button_press_start

    logger.info("紧急倒计时开始...")

    for i in range(20, 0, -1):
        if not running:
            break

        logger.info(f"紧急倒计时: {i}秒")
        time.sleep(1)

        if button_press_start is not None:
            press_duration = time.time() - button_press_start
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
    add_voice("紧急求助！紧急求助！需要帮助！")

    # 启动SOS闪烁（非阻塞）
    start_led_sos()

    while emergency_mode and running:
        add_voice("需要帮助")
        time.sleep(2)  # 语音间隔，不阻塞LED


# ==================== 按钮处理 ====================
last_button_state = 0
button_press_start = None


def button_monitor():
    """按钮监控线程"""
    global current_mode, button_press_start, fall_detected, emergency_mode
    global exit_sport_countdown, last_button_state, message_showing
    global last_click_time, long_press_2s_voiced

    # 长按触发标志，避免重复触发
    long_press_triggered = False

    while running:
        try:
            if button:
                current_state = button.value()
            else:
                time.sleep(0.05)
                continue

            # 按下
            if current_state == 1 and last_button_state == 0:
                button_press_start = time.time()
                long_press_triggered = False
                long_press_2s_voiced = False  # 重置2秒语音标志

            # 按钮保持按下状态 - 检测长按
            elif current_state == 1 and last_button_state == 1:
                if button_press_start is not None:
                    press_duration = time.time() - button_press_start

                    # 运动模式：连续长按4秒，中途2秒语音提示
                    if current_mode == MODE_SPORT and not long_press_triggered:
                        # 达到2秒：播报语音提示
                        if press_duration >= 2.0 and not long_press_2s_voiced:
                            long_press_2s_voiced = True
                            add_voice("即将退出运动模式，继续长按2秒后退出")
                            logger.info("运动模式：长按2秒，语音提示已播报")

                        # 达到4秒：确认退出
                        if press_duration >= 4.0:
                            long_press_triggered = True
                            old_mode = current_mode
                            change_mode_internal(MODE_LIFE)
                            logger.info(f"模式切换: {MODE_NAMES[old_mode]} → {MODE_NAMES[current_mode]}")
                            button_press_start = None

                    # 其他情况：使用原来的2秒阈值
                    elif not long_press_triggered and press_duration >= long_press_threshold:
                        long_press_triggered = True

                        # 紧急模式取消
                        if fall_detected or emergency_mode:
                            fall_detected = False
                            emergency_mode = False
                            stop_led_breathing()  # 停止SOS灯
                            add_voice("紧急模式已取消")
                            logger.info("按钮长按取消紧急模式")
                            stop_all_voice()
                            button_press_start = None

                        # 消息显示中
                        elif message_showing:
                            exit_message_scroll()
                            logger.info("按钮长按退出消息显示")
                            button_press_start = None

                        # 生活/会议模式：直接切换
                        else:
                            old_mode = current_mode
                            current_mode = (current_mode + 1) % 4
                            logger.info(f"模式切换: {MODE_NAMES[old_mode]} → {MODE_NAMES[current_mode]}")

                            if old_mode == MODE_MEETING:
                                exit_meeting_mode()

                            stop_all_voice()
                            update_ui_mode()

                            if current_mode == MODE_MEETING:
                                enter_meeting_mode()
                            elif current_mode == MODE_SPORT:
                                # 运动模式环境检查
                                try:
                                    if dht11:
                                        temp = round(dht11.temp_c() * 0.8, 1)
                                        if temp is not None:
                                            if temp < 10:
                                                add_voice(f"当前温度{int(temp)}度，较冷，请注意保暖")
                                            elif temp > 30:
                                                add_voice(f"当前温度{int(temp)}度，较热，请注意补水")
                                except:
                                    pass
                            button_press_start = None

            # 释放
            elif current_state == 0 and last_button_state == 1:
                if button_press_start is not None:
                    press_duration = time.time() - button_press_start
                    current_time = time.time()

                    # 如果之前没有触发长按，作为短按处理
                    if not long_press_triggered and press_duration < long_press_threshold:
                        # 紧急模式/消息显示中：无效
                        if fall_detected or emergency_mode or message_showing:
                            pass
                        else:
                            # 双击检测
                            if last_click_time is not None:
                                click_interval = current_time - last_click_time
                                if click_interval <= double_click_interval:
                                    # 双击触发播报
                                    if current_mode == MODE_LIFE:
                                        report_life_mode_status()
                                    elif current_mode == MODE_SPORT:
                                        report_sport_mode_status()
                                    last_click_time = None  # 重置，避免三次点击触发多次
                                else:
                                    # 超过间隔，作为新的单击
                                    last_click_time = current_time
                            else:
                                # 第一次点击
                                last_click_time = current_time


                    button_press_start = None

            last_button_state = current_state

        except Exception as e:
            logger.error(f"按钮监控错误: {e}")

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
class OfflineManager:
    """离线数据管理器"""

    CACHE_DIR = "/root/.anklet"
    CACHE_FILE = "cache.json"
    PENDING_FILE = "pending.json"
    DEVICE_FILE = "device_id.json"

    def __init__(self):
        # 开机默认离线模式
        self.is_online = False
        self.pending_data = []
        self.cache_data = {}
        self.device_id = self._get_or_create_device_id()

        try:
            os.makedirs(self.CACHE_DIR, exist_ok=True)
        except:
            pass

        self._load_cache()
        self._load_pending()

    def _get_or_create_device_id(self):
        try:
            if os.path.exists(self.DEVICE_FILE):
                with open(self.DEVICE_FILE, 'r') as f:
                    return f.read().strip()
            else:
                import uuid
                device_id = str(uuid.uuid4())
                with open(self.DEVICE_FILE, 'w') as f:
                    f.write(device_id)
                return device_id
        except:
            return "unknown"

    def _load_cache(self):
        try:
            cache_path = os.path.join(self.CACHE_DIR, self.CACHE_FILE)
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    self.cache_data = json.load(f)
        except:
            self.cache_data = {}

    def _load_pending(self):
        try:
            pending_path = os.path.join(self.CACHE_DIR, self.PENDING_FILE)
            if os.path.exists(pending_path):
                with open(pending_path, 'r') as f:
                    self.pending_data = json.load(f) or []
        except:
            self.pending_data = []

    def _save_cache(self):
        try:
            cache_path = os.path.join(self.CACHE_DIR, self.CACHE_FILE)
            with open(cache_path, 'w') as f:
                json.dump(self.cache_data, f, ensure_ascii=False)
        except:
            pass

    def _save_pending(self):
        try:
            pending_path = os.path.join(self.CACHE_DIR, self.PENDING_FILE)
            with open(pending_path, 'w') as f:
                json.dump(self.pending_data, f, ensure_ascii=False)
        except:
            pass

    def update_cache(self, data):
        today = datetime.now().strftime("%Y-%m-%d")

        if today not in self.cache_data:
            self.cache_data[today] = {
                "steps": 0,
                "carbon": 0,
                "duration": 0,
                "last_update": None
            }

        current_steps = data.get("step", 0)
        last_steps = self.cache_data[today].get("steps", 0)

        if current_steps >= last_steps:
            self.cache_data[today]["steps"] = current_steps
            self.cache_data[today]["carbon"] = data.get("carbon_reduce", 0)
            self.cache_data[today]["duration"] = data.get("sport_time_today", 0)
            self.cache_data[today]["last_update"] = datetime.now().isoformat()

        self._save_cache()

    def set_online_status(self, is_online):
        """设置在线状态"""
        was_offline = not self.is_online
        self.is_online = is_online
        if was_offline and is_online:
            logger.info("已切换到在线模式")
        elif was_offline and not is_online:
            # 保持在离线状态，不打印（避免频繁打印）
            pass
        elif not was_offline and not is_online:
            # 从在线切换到离线
            logger.info("已切换到离线模式")

    def try_connect(self):
        """尝试连接服务器，返回是否成功（无重试）"""
        try:
            # 创建禁用重试的session
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            session = requests.Session()
            retry = Retry(total=0, connect=0, read=0, redirect=0)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            # 发送请求
            response = session.get(
                f"{SERVER_URL}/api/status",
                timeout=3
            )
            if response.status_code == 200:
                return True
        except Exception:
            pass
        return False

    def sync_all_pending(self):
        """一次性同步所有pending数据"""
        if not self.is_online or not self.pending_data:
            return 0

        synced_count = 0

        try:
            # 使用批量同步API
            response = requests.post(
                f"{SERVER_URL}/api/sync_records",
                json={"records": self.pending_data},
                timeout=10
            )
            if response.status_code == 200:
                result = response.json()
                synced_count = result.get("synced_count", 0)
                # 删除已同步的数据
                self.pending_data = []
                self._save_pending()
                logger.info(f"批量同步成功: {synced_count} 条记录")
        except Exception as e:
            logger.warning(f"批量同步失败: {e}")

        return synced_count


offline_manager = OfflineManager()


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
                "pace_str": calculate_pace() if current_mode == MODE_SPORT else "--'--\"",
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

    if message_showing:
        return

    old_mode = current_mode

    if old_mode == MODE_SPORT and new_mode != MODE_SPORT:
        if sport_duration > 30:
            record_sport_session()
        # 重置配速显示和计时器
        current_pace_str = "--'--\""
        gps_speed_read_time = None
        gps_current_speed = None
        step_pace_start_time = None
        step_pace_last_step = 0
        # 停止GNSS和呼吸灯
        gnss_manager.stop()
        stop_led_breathing()

    if old_mode == MODE_MEETING:
        exit_meeting_mode()

    stop_all_voice()
    current_mode = new_mode

    add_voice(f"切换到{MODE_NAMES[current_mode]}")
    update_ui_mode()

    if current_mode == MODE_MEETING:
        enter_meeting_mode()


def handle_command(cmd):
    """处理服务器命令"""
    global current_mode, led_brightness

    command = cmd.get("command")

    if command == "change_mode":
        if message_showing:
            exit_message_scroll()

        new_mode = cmd.get("mode", current_mode)
        if 0 <= new_mode <= 3:
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
class GNSSManager:
    """GNSS速度管理器 - 仅用于获取速度计算配速"""

    def __init__(self, cfg=None):
        default_cfg = {
            "enabled": True,
        }
        if cfg:
            default_cfg.update(cfg)
        self.config = default_cfg

        self.gnss = None
        self.is_active = False

    def initialize(self):
        if not GNSS_AVAILABLE or not self.config["enabled"]:
            return False

        try:
            self.gnss = DFRobot_GNSS_I2C(bus=0, addr=0x20)

            if self.gnss.begin() == False:
                logger.error("GNSS初始化失败")
                return False

            self.gnss.enable_power()
            self.gnss.set_gnss(GPS_BeiDou_GLONASS)
            logger.info("GNSS模块初始化成功")
            return True

        except Exception as e:
            logger.warning(f"GNSS初始化异常: {e}")
            return False

    def start(self):
        """启动GNSS"""
        if not GNSS_AVAILABLE or not self.config["enabled"]:
            return

        if self.is_active:
            return

        self.is_active = True

        if not self.initialize():
            return

        logger.info("GNSS已启动")

    def stop(self):
        """停止GNSS"""
        self.is_active = False
        if self.gnss:
            try:
                self.gnss.disable_power()
            except:
                pass

    def get_speed(self):
        """获取速度(km/h)，无效返回None"""
        if not self.is_active or not self.gnss:
            return None

        try:
            # 获取速度（km/h）
            speed = self.gnss.get_speed()
            if speed > 0:
                return speed  # km/h
        except:
            pass
        return None


gnss_manager = GNSSManager()


# 主循环采样统计计数器
_sample_stats_counter = 0


# ==================== 主循环 ====================
def main_loop():
    """主循环"""
    global _sample_stats_counter

    while running:
        try:
            # 会议模式不显示任何内容
            if not message_showing:
                if current_mode != MODE_MEETING and gui:
                    # 更新时间
                    if 'time_text' in ui_elements:
                        ui_elements['time_text'].config(text=datetime.now().strftime('%H:%M:%S'))

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
        button = Pin(PIN_BUTTON, Pin.IN)
        logger.info("按钮初始化成功")
        knob = Pin(PIN_KNOB, Pin.ANALOG)
        logger.info("旋钮初始化成功")
        led_strip = NeoPixel(Pin(PIN_LED), LED_COUNT)
        led_strip.brightness(led_brightness)
        logger.info("LED初始化成功")

        tts = DFRobot_SpeechSynthesis_I2C()
        tts.begin(tts.V2)
        tts.set_voice(9)
        tts.set_speed(5)
        tts.set_tone(5)
        tts.set_sound_type(tts.FEMALE2)

        gui = GUI()
    else:
        logger.warning("运行在模拟模式")

    init_ui()

    logger.info("硬件初始化完成")
    logger.info(f"sensors模块: {'已加载' if sensors_module_available else '未加载'}")
    logger.info(f"utils模块: {'已加载' if utils_available else '未加载'}")
    logger.info("=" * 60)

    try:
        threads = [
            threading.Thread(target=voice_thread, daemon=True, name="voice"),
            threading.Thread(target=knob_thread, daemon=True, name="knob"),
            threading.Thread(target=button_monitor, daemon=True, name="button"),
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
