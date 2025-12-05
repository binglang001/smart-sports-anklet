# -*- coding: UTF-8 -*-
"""
行空板M10运动腿环程序
"""

import time
import threading
import math
import signal
import sys
import requests
from datetime import datetime, timedelta
from pinpong.board import Board, Pin, DHT11, NeoPixel, ADC
from pinpong.extension.unihiker import *
from pinpong.libs.dfrobot_speech_synthesis import DFRobot_SpeechSynthesis_I2C
from unihiker import GUI
from traceback import TracebackException

# ==================== 配置 ====================
SERVER_URL = "http://your-server-ip:5000"
UPDATE_INTERVAL = 2

# 姿态检测配置
POSTURE_AXIS = "x"
POSTURE_THRESHOLD = 0.49
SITTING_DIRECTION = "less"

# 引脚定义
PIN_DHT11 = Pin.P23
PIN_BUTTON = Pin.P24
PIN_KNOB = Pin.P22
PIN_LED = Pin.P21

LED_COUNT = 7

# 模式定义
MODE_LIFE = 0
MODE_SPORT = 1
MODE_CYCLING = 2
MODE_MEETING = 3
MODE_NAMES = ["生活模式", "运动模式", "骑行模式", "会议模式"]
MODE_COLORS = ["#000000", "#000000", "#000000", "#000000"]
LINE_COLORS = ["#00FF00", "#FFFF00", "#FF8800", "#8888FF"]

# 全局变量
current_mode = MODE_LIFE
last_temp = 25
last_humi = 50
led_brightness = 128
emergency_mode = False
voice_queue = []
sitting_start_time = None
posture_history = []
movement_history = []
fall_detected = False
running = True
voice_enabled = True
current_posture = "unknown"
sport_start_time = None
sport_time_today = 0
activity_hours = set()
last_activity_hour = -1
sitting_duration = 0
sport_duration = 0
last_movement_time = None
exit_sport_countdown = False
button_press_start = None
long_press_threshold = 1.5
sitting_remind_duration = 3600
step_count = 0
acc_history = []
carbon_reduce_count = 0
mode_text_position = [[8, 10], [68, 40], [128, 70], [188, 100]]
led_position = 0

# 消息显示相关
message_showing = False
current_message = ""
message_scroll_thread = None

# 会议模式显示控制
meeting_black_rect = None

# UI元素引用
ui_elements = {}

# ==================== 退出处理 ====================
def exit_handler(signum=None, frame=None):
    """程序退出处理"""
    global running
    print("\n正在清理资源...")
    running = False
    
    try:
        for i in range(LED_COUNT):
            led_strip[i] = (0, 0, 0)
        gui.clear()
        print("清理完成，程序退出")
    except:
        pass
    
    sys.exit(0)

signal.signal(signal.SIGINT, exit_handler)
signal.signal(signal.SIGTERM, exit_handler)

# 全局硬件对象
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
    
    gui.clear()
    
    ui_elements['title'] = gui.draw_text(x=120, y=10, text="运动腿环系统", 
                                         color="#FFFFFF", font_size=18, anchor="n")
    
    ui_elements['mode_back_line'] = gui.draw_line(x0=-55,y0=0,x1=280,y1=170,width=75,color=LINE_COLORS[current_mode])
    
    ui_elements['mode_text'] = [gui.draw_text(x=mode_text_position[x][0], y=mode_text_position[x][1], text=MODE_NAMES[current_mode][x], 
                                             color=MODE_COLORS[current_mode], 
                                             font_size=36) for x in range(4)]
    print(ui_elements['mode_text'])

    ui_elements['time_text'] = gui.draw_text(x=110, y=0, text="--:--:--", 
                                            color="#9A9A01", font_size=23)
    
    ui_elements['temp_text'] = gui.draw_text(x=0, y=135, text="温度: --°C", 
                                            color="#FF4444", font_size=17)
    ui_elements['humi_text'] = gui.draw_text(x=0, y=160, text="湿度: --%", 
                                            color="#4444FF", font_size=17)
    
    # 生活模式特有元素：坐姿
    ui_elements['sitting_text'] = gui.draw_text(x=0, y=185, text="坐姿: 0分钟", 
                                               color="#00FFFF", font_size=17)
    
    # 运动模式特有元素：配速
    ui_elements['pace_text'] = gui.draw_text(x=0, y=185, text="配速: --'--\"", 
                                            color="#00FF00", font_size=17, 
                                            state='hidden')
    
    # 运动模式特有元素：运动时间
    ui_elements['sport_time_text'] = gui.draw_text(x=0, y=210, text="运动: 0分钟", 
                                                   color="#FFAA00", font_size=17, 
                                                   state='hidden')
    
    # 运动模式特有元素：步数
    ui_elements['step_text'] = gui.draw_text(x=0, y=235, text="步数: 0步", 
                                            color="#FFEE00", font_size=20, 
                                            state='hidden')
    
    # 运动模式特有元素：减碳
    ui_elements['carbon_reduce_text'] = gui.draw_text(x=0, y=260, text="◆约为减碳: 0g", 
                                            color="#00FF00", font_size=19,
                                            state='hidden')
    
    ui_elements['status_text'] = gui.draw_text(x=150, y=300, text="状态: 初始化中...", 
                                              color="#797878", font_size=10)

def update_ui_mode():
    """根据模式更新UI显示"""
    if message_showing:
        return
    
    if current_mode == MODE_LIFE:
        ui_elements['sitting_text'].config(state='normal')
        ui_elements['pace_text'].config(state='hidden')
        ui_elements['sport_time_text'].config(state='hidden')
        ui_elements['step_text'].config(state='hidden')
        ui_elements['carbon_reduce_text'].config(state='hidden')
    elif current_mode in [MODE_SPORT, MODE_CYCLING]:
        ui_elements['sitting_text'].config(state='hidden')
        ui_elements['pace_text'].config(state='normal')
        ui_elements['sport_time_text'].config(state='normal')
        ui_elements['step_text'].config(state='normal')
        ui_elements['carbon_reduce_text'].config(state='normal')
    elif current_mode == MODE_MEETING:
        # 会议模式下UI元素正常显示，但会被黑屏遮住
        pass

# ==================== 消息滚动显示 ====================
def show_message_scroll(message):
    """显示滚动消息"""
    global message_showing, current_message, message_scroll_thread
    
    stop_all_voice()
    
    # 停止旧的滚动线程
    if message_scroll_thread and message_scroll_thread.is_alive():
        message_showing = False
        time.sleep(0.3)
    
    current_message = message
    
    # 隐藏所有UI元素
    for key in ui_elements:
        try:
            ui_elements[key].config(state='hidden')
        except:
            pass
    
    # 给GUI一点时间处理隐藏操作
    time.sleep(0.1)
    
    # 设置为显示状态
    message_showing = True
    
    # 播放语音
    add_voice(message)
    
    # 启动滚动线程
    message_scroll_thread = threading.Thread(target=scroll_message_thread, 
                                            args=(message,), daemon=True)
    message_scroll_thread.start()

def scroll_message_thread(message):
    """滚动消息线程 - 竖向排列，循环滚动"""
    global message_showing
    
    # 确保GUI已准备好
    time.sleep(0.1)
    
    # 创建白色背景
    white_bg = gui.fill_rect(x=0, y=0, w=240, h=320, color="#FFFFFF")
    
    # 标点符号列表
    punctuation = ['，', '。', '、', '！', '？', '；', '：', '…', ',', '.', '!', '?', ';', ':', '\'', '"', '"', '"', ''', ''']
    
    # 处理消息：将标点符号附加到前一个字符上
    processed_chars = []
    temp_char = ""
    
    for char in message:
        if char in punctuation:
            # 标点符号附加到前一个字符
            temp_char += char
        else:
            # 普通字符：先保存之前的字符（如果有），然后开始新字符
            if temp_char:
                processed_chars.append(temp_char)
            temp_char = char
    
    # 添加最后一个字符
    if temp_char:
        processed_chars.append(temp_char)
    
    # 将字符转换为竖向排列
    vertical_message = '\n'.join(processed_chars)
    
    # 根据是否为紧急模式选择颜色
    text_color = "#FF0000" if emergency_mode else "#000000"
    
    # 字体大小140
    font_size = 140
    
    # 创建滚动文本
    if "," in vertical_message or "，" in vertical_message:
        scroll_text = gui.draw_text(x=200, y=320, text=vertical_message, 
                                color=text_color, font_size=font_size, 
                                anchor="n")
    else:
        scroll_text = gui.draw_text(x=120, y=320, text=vertical_message, 
                                    color=text_color, font_size=font_size, 
                                    anchor="n")
    
    # 计算文本总高度（行高约为字体大小的1.2倍）
    line_height = int(font_size * 1.2)
    text_height = len(processed_chars) * line_height
    
    y_pos = 320
    
    while message_showing and running and current_message == message:
        y_pos -= 2
        
        # 当文字完全滚出屏幕后，从底部重新开始
        if y_pos < -(text_height + 320):
            y_pos = 320
        
        try:
            scroll_text.config(y=y_pos)
        except:
            break
        
        time.sleep(0.03)
    
    # 清理
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
    
    # 清空屏幕并重新初始化UI
    gui.clear()
    init_ui()
    
    # 根据当前模式更新UI
    ui_elements['mode_back_line'].config(color=LINE_COLORS[current_mode])
    for t, x in enumerate(ui_elements['mode_text']):
        x.config(text=MODE_NAMES[current_mode][t], 
                                   color=MODE_COLORS[current_mode])
    update_ui_mode()
    
    # 如果是会议模式，重新显示黑屏
    if current_mode == MODE_MEETING:
        enter_meeting_mode()

# ==================== 语音合成 ====================
def add_voice(text):
    """添加语音到队列"""
    if voice_enabled and current_mode != MODE_MEETING:
        voice_queue.append(text)
        print(f"[语音] {text}")

def stop_all_voice():
    """停止所有语音"""
    voice_queue.clear()
    try:
        tts.stop()
    except:
        pass

def voice_thread():
    """语音播报线程"""
    while running:
        if voice_queue and voice_enabled and current_mode != MODE_MEETING:
            text = voice_queue.pop(0)
            try:
                tts.speak(text)
                time.sleep(0.5)
            except Exception as e:
                print(f"语音播放错误: {e}")
        time.sleep(0.1)

# ==================== LED控制 ====================
def set_led_color(r, g, b):
    """设置所有LED颜色"""
    try:
        for i in range(LED_COUNT):
            led_strip[i] = (int(r), 
                           int(g), 
                           int(b))
    except:
        pass

def led_flash(r, g, b, interval=0.5):
    """LED闪烁效果"""
    set_led_color(r, g, b)
    time.sleep(interval)
    set_led_color(0, 0, 0)
    time.sleep(interval)

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

# ==================== 运动检测 ====================
def detect_fall():
    """检测摔倒"""
    try:
        ax = accelerometer.get_x()
        ay = accelerometer.get_y()
        az = accelerometer.get_z()
        
        total_acc = math.sqrt(ax*ax + ay*ay + az*az)
        
        if total_acc < 0.3:
            print(f"[摔倒检测] 自由落体: {total_acc:.2f}")
            return True
        
        if total_acc > 2.9:
            print(f"[摔倒检测] 强烈冲击: {total_acc:.2f}")
            return True
            
        if abs(ax) > 2.3 or abs(ay) > 2.3 or abs(az) > 2.5:
            print(f"[摔倒检测] 单轴突变: x={ax:.2f}, y={ay:.2f}, z={az:.2f}")
            return True
        
        if hasattr(detect_fall, 'last_total'):
            acc_change = abs(total_acc - detect_fall.last_total)
            if acc_change > 2.0:
                print(f"[摔倒检测] 加速度突变: {acc_change:.2f}")
                return True
        detect_fall.last_total = total_acc
            
    except Exception as e:
        print(f"摔倒检测错误: {e}")
    return False

def detect_posture():
    """检测姿态"""
    global posture_history, current_posture
    
    try:
        ax = accelerometer.get_x()
        ay = accelerometer.get_y()
        az = accelerometer.get_z()
        
        if POSTURE_AXIS == "x":
            axis_value = ax
        elif POSTURE_AXIS == "y":
            axis_value = ay
        else:
            axis_value = az
        
        posture_history.append(axis_value)
        if len(posture_history) > 20:
            posture_history.pop(0)
        
        avg_value = sum(posture_history) / len(posture_history) if posture_history else axis_value
        
        if SITTING_DIRECTION == "greater":
            new_posture = "sitting" if avg_value > POSTURE_THRESHOLD else "standing"
        else:
            new_posture = "sitting" if avg_value < POSTURE_THRESHOLD else "standing"
        
        if int(time.time()) % 5 == 0 and len(posture_history) == 20:
            print(f"[姿态] {POSTURE_AXIS.upper()}轴={avg_value:.3f}, 阈值={POSTURE_THRESHOLD:.3f}, 状态={current_posture}")
        
        if new_posture != current_posture:
            if not hasattr(detect_posture, 'change_count'):
                detect_posture.change_count = 0
                detect_posture.target_posture = new_posture
            
            if detect_posture.target_posture == new_posture:
                detect_posture.change_count += 1
                if detect_posture.change_count >= 3:
                    current_posture = new_posture
                    detect_posture.change_count = 0
                    print(f"[姿态切换] → {current_posture}")
                    return True
            else:
                detect_posture.target_posture = new_posture
                detect_posture.change_count = 1
            
    except Exception as e:
        print(f"姿态检测错误: {e}")
    
    return False

def calculate_pace():
    """计算配速（1000米速度）"""
    global movement_history
    try:
        acc_strength = accelerometer.get_strength()
        current_time = time.time()
        
        movement_history.append((current_time, acc_strength))
        movement_history = [(t, a) for t, a in movement_history 
                          if current_time - t < 60]
        
        if len(movement_history) > 10:
            steps = 0
            for i in range(1, len(movement_history) - 1):
                if (movement_history[i][1] > movement_history[i-1][1] and
                    movement_history[i][1] > movement_history[i+1][1] and
                    movement_history[i][1] > 1.5):
                    steps += 1
            
            if steps > 0:
                steps_per_min = steps
                stride = 2.5
                distance_per_min = steps_per_min * stride
                if distance_per_min > 0:
                    min_per_1000m = 1000 / distance_per_min
                    minutes = int(min_per_1000m)
                    seconds = int((min_per_1000m - minutes) * 60)
                    return f"{minutes}'{seconds:02d}\""
    except:
        pass
    return "--'--\""

def calculate_step_and_carbon():
    """计算步数和减碳"""
    global step_count, acc_history, carbon_reduce_count
    try:
        acc_strength = (accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_strength())
        
        acc_history.append(acc_strength)
        
        if (len(acc_history) > 2 and
            abs(acc_history[-2][0] - acc_history[-1][0]) + abs(acc_history[-3][0] - acc_history[-2][0]) > 0.5 or
            abs(acc_history[-2][1] - acc_history[-1][1]) + abs(acc_history[-3][1] - acc_history[-2][1]) > 0.6):
            step_count += 1
            print(f"步数+1，加速度：本次{acc_history[-1]}\n上次{acc_history[-2]}")
            send_carbon()
            carbon_reduce_count += 0.0014
            return (step_count, carbon_reduce_count)

    except:
        pass
    return (step_count, carbon_reduce_count)

def detect_movement():
    """检测是否有运动"""
    global last_movement_time
    try:
        acc_strength = accelerometer.get_strength()
        if acc_strength > 1.3:
            last_movement_time = time.time()
            return True
    except:
        pass
    return False

# ==================== 运动时长统计 ====================
def update_sport_time():
    """更新运动时长"""
    global sport_start_time, sport_time_today, sport_duration
    
    if current_mode in [MODE_SPORT, MODE_CYCLING]:
        if sport_start_time is None:
            sport_start_time = time.time()
            sport_duration = 0
        else:
            elapsed = int(time.time() - sport_start_time)
            sport_time_today += elapsed
            sport_duration += elapsed
            sport_start_time = time.time()
    else:
        if sport_start_time is not None:
            record_sport_session()
        sport_start_time = None
        sport_duration = 0

def record_sport_session():
    """记录运动会话"""
    global sport_duration
    if sport_duration > 60:
        try:
            pace = calculate_pace()
            step_and_carbon = calculate_step_and_carbon()
            record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "mode": "运动" if current_mode == MODE_SPORT else "骑行",
                "duration": sport_duration,
                "pace": pace,
                "step": step_and_carbon[0],
                "carbon_reduce": step_and_carbon[1]
            }
            requests.post(f"{SERVER_URL}/api/sport_records", 
                         json=record, timeout=5)
            print(f"[运动记录] 已记录: {record}")
        except Exception as e:
            print(f"记录运动失败: {e}")
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
            print("已重置今日统计数据")

# ==================== 运动静止检测 ====================
def sport_idle_monitor():
    """运动模式静止监控"""
    global exit_sport_countdown, last_movement_time
    
    while running:
        time.sleep(1)
        
        if current_mode in [MODE_SPORT, MODE_CYCLING] and not emergency_mode:
            if last_movement_time is None:
                last_movement_time = time.time()
            
            idle_time = time.time() - last_movement_time
            
            if idle_time > 60 and not exit_sport_countdown:
                exit_sport_countdown = True
                add_voice("检测到您已静止一分钟，是否退出运动模式？请长按按钮取消")
                
                countdown_start = time.time()
                while running and exit_sport_countdown:
                    if time.time() - countdown_start > 20:
                        if current_mode in [MODE_SPORT, MODE_CYCLING]:
                            old_mode = current_mode
                            change_mode_internal(MODE_LIFE)
                            add_voice("已自动退出运动模式")
                        exit_sport_countdown = False
                        break
                    time.sleep(0.5)
        last_movement_time = time.time()

# ==================== 会议模式屏幕控制 ====================
def enter_meeting_mode():
    """进入会议模式"""
    global meeting_black_rect
    
    print("[会议模式] 进入会议模式，显示黑屏")
    
    # 重新创建黑色遮罩
    meeting_black_rect = gui.fill_rect(x=0, y=0, w=240, h=320, 
                                      color="#000000")
    
    set_led_color(0, 0, 0)

def exit_meeting_mode():
    """退出会议模式"""
    global meeting_black_rect
    
    print("[会议模式] 退出会议模式，恢复显示")
    
    # 删除黑色遮罩
    if meeting_black_rect is not None:
        try:
            meeting_black_rect.remove()
            print("[会议模式] 遮罩已删除")
        except:
            pass
    
    meeting_black_rect = None

# ==================== 模式处理 ====================
def handle_life_mode():
    """生活模式"""
    global last_temp, last_humi, sitting_remind_duration, led_position
    
    if message_showing:
        return
    
    try:
        temp = round(dht11.temp_c() * 0.8, 1)
        humi = dht11.humidity()
        
        if temp is not None and humi is not None:
            ui_elements['temp_text'].config(text=f"温度: {temp}°C")
            ui_elements['humi_text'].config(text=f"湿度: {humi}%")
            
            if abs(temp - last_temp) > 5:
                if temp > last_temp:
                    add_voice(f"温度上升，当前{temp}度，请注意减衣")
                else:
                    add_voice(f"温度下降，当前{temp}度，请注意保暖")
                last_temp = temp
                last_humi = humi
            
            color = update_led_by_temp_humi(temp, humi)
            led_strip[led_position] = (0, 0, 0)
            led_position += 1
            if led_position == 7:
                led_position = 0
            led_strip[led_position] = (color[0], color[1], color[2])
    except:
        pass
    
    detect_posture()
    update_sitting_duration()
    
    sitting_min = sitting_duration // 60
    ui_elements['sitting_text'].config(text=f"坐姿: {sitting_min}分钟")
    
    if sitting_duration > 0 and sitting_duration >= sitting_remind_duration:
        if sitting_duration % sitting_remind_duration < 2:
            add_voice("您已经坐了很久，请站起来活动一下")
            ui_elements['status_text'].config(text="提醒: 请起身活动", color="#FFAA00")
    else:
        ui_elements['status_text'].config(text="状态: 正常", color="#797878")
    
    update_activity_hours()

def handle_sport_mode():
    """运动模式"""
    global fall_detected, emergency_mode
    
    if message_showing:
        return
    
    led_flash(255, 255, 0, 0.5)
    
    detect_movement()
    
    pace_str = calculate_pace()
    ui_elements['pace_text'].config(text=f"配速: {pace_str}")
    
    sport_min = sport_duration // 60
    ui_elements['sport_time_text'].config(text=f"运动: {sport_min}分钟")

    steps, carbon_reduces = calculate_step_and_carbon()
    ui_elements['step_text'].config(text=f"步数: {steps}步")
    ui_elements['carbon_reduce_text'].config(text=f"◆约为减碳: {round(carbon_reduces, 3)}g")
    
    if detect_fall() and not fall_detected:
        print("[运动模式] 检测到摔倒！")
        fall_detected = True
        ui_elements['status_text'].config(text="检测到摔倒！", color="#FF0000")
        add_voice("检测到摔倒，是否需要帮助？长按按钮取消警报")
        threading.Thread(target=emergency_countdown, daemon=True).start()
    
    update_sport_time()

def handle_cycling_mode():
    """骑行模式"""
    global fall_detected, emergency_mode
    
    if message_showing:
        return
    
    led_flash(255, 140, 0, 0.5)
    
    detect_movement()
    
    pace_str = calculate_pace()
    ui_elements['pace_text'].config(text=f"配速: {pace_str}")
    
    sport_min = sport_duration // 60
    ui_elements['sport_time_text'].config(text=f"运动: {sport_min}分钟")
    
    if detect_fall() and not fall_detected:
        print("[骑行模式] 检测到摔倒！")
        fall_detected = True
        ui_elements['status_text'].config(text="检测到摔倒！", color="#FF0000")
        add_voice("检测到摔倒，是否需要帮助？长按按钮取消警报")
        threading.Thread(target=emergency_countdown, daemon=True).start()
    
    update_sport_time()

def handle_meeting_mode():
    """会议模式"""
    pass

def emergency_countdown():
    """紧急倒计时"""
    global emergency_mode, fall_detected, button_press_start
    
    print("[紧急倒计时] 开始倒计时...")
    
    for i in range(20, 0, -1):
        if not running:
            break
        
        ui_elements['status_text'].config(text=f"紧急倒计时: {i}秒", color="#FF0000")
        print(f"[紧急倒计时] {i}秒")
        time.sleep(1)
        
        if button_press_start is not None:
            press_duration = time.time() - button_press_start
            if press_duration >= long_press_threshold:
                fall_detected = False
                add_voice("紧急警报已取消")
                ui_elements['status_text'].config(text="状态: 正常", color="#797878")
                print("[紧急倒计时] 长按已取消")
                return
    
    emergency_mode = True
    print("[紧急倒计时] 超时，进入紧急模式")
    handle_emergency()

def handle_emergency():
    """处理紧急情况"""
    print("[紧急模式] 启动紧急求助")
    add_voice("紧急求助！紧急求助！需要帮助！")
    ui_elements['status_text'].config(text="紧急模式！", color="#FF0000")
    
    while emergency_mode and running:
        add_voice("需要帮助")
        led_flash(255, 0, 0, 0.2)
        time.sleep(0.2)

# ==================== 按钮处理 ====================
last_button_state = 0
button_press_start = None

def button_monitor():
    """按钮监控线程"""
    global current_mode, button_press_start, fall_detected, emergency_mode
    global exit_sport_countdown, last_button_state, message_showing
    
    while running:
        try:
            current_state = button.value()
            
            if current_state == 1 and last_button_state == 0:
                button_press_start = time.time()
                
            elif current_state == 0 and last_button_state == 1:
                if button_press_start is not None:
                    press_duration = time.time() - button_press_start
                    
                    if press_duration >= long_press_threshold:
                        if fall_detected or emergency_mode:
                            fall_detected = False
                            emergency_mode = False
                            add_voice("紧急模式已取消")
                            ui_elements['status_text'].config(text="状态: 正常", color="#797878")
                            print("[按钮] 长按取消紧急模式")
                            stop_all_voice()
                        elif exit_sport_countdown:
                            exit_sport_countdown = False
                            add_voice("已取消退出运动模式")
                            print("[按钮] 长按取消退出运动模式")
                        elif message_showing:
                            exit_message_scroll()
                            print("[按钮] 长按退出消息显示")
                        else:
                            try:
                                temp = round(dht11.temp_c() * 0.8, 1)
                                humi = dht11.humidity()
                                add_voice(f"当前状态：温度{temp}度，湿度{humi}%")
                            except:
                                pass
                    else:
                        # 短按切换模式（但消息显示时、紧急状态、退出倒计时时不切换）
                        if not (fall_detected or emergency_mode or exit_sport_countdown or message_showing):
                            old_mode = current_mode
                            current_mode = (current_mode + 1) % 4
                            
                            print(f"[按钮] 模式切换: {MODE_NAMES[old_mode]} → {MODE_NAMES[current_mode]}")
                            
                            if old_mode == MODE_MEETING:
                                exit_meeting_mode()
                            
                            stop_all_voice()
                            
                            ui_elements['mode_back_line'].config(color=LINE_COLORS[current_mode])
                            for t, x in enumerate(ui_elements['mode_text']):
                                x.config(text=MODE_NAMES[current_mode][t], 
                                                        color=MODE_COLORS[current_mode])
                            add_voice(f"切换到{MODE_NAMES[current_mode]}")
                            
                            update_ui_mode()
                            
                            if current_mode == MODE_MEETING:
                                enter_meeting_mode()
                            elif current_mode in [MODE_SPORT, MODE_CYCLING]:
                                try:
                                    temp = round(dht11.temp_c() * 0.8, 1)
                                    if temp:
                                        if temp < 10:
                                            add_voice(f"当前温度{temp}度，较冷，请注意保暖")
                                        elif temp > 35:
                                            add_voice(f"当前温度{temp}度，较热，请注意补水")
                                        else:
                                            add_voice(f"温度{temp}度，运动条件良好")
                                except:
                                    pass
                    
                    button_press_start = None
            
            last_button_state = current_state
            
        except Exception as e:
            print(f"按钮监控错误: {e}")
        
        time.sleep(0.05)

# ==================== 旋钮处理 ====================
def knob_thread():
    """旋钮控制线程"""
    global led_brightness
    
    while running:
        if current_mode != MODE_MEETING:
            try:
                knob_value = knob.read_analog()
                led_brightness = int(knob_value * 255 / 4095)
                led_strip.brightness(led_brightness)
            except:
                pass
        time.sleep(0.1)

# ==================== HTTP通信 ====================
def send_status():
    """发送状态到服务器"""
    global sitting_remind_duration
    try:
        data = {
            "mode": current_mode,
            "temperature": last_temp,
            "humidity": last_humi,
            "brightness": led_brightness,
            "posture": current_posture,
            "pace": 0,
            "pace_str": calculate_pace() if current_mode in [MODE_SPORT, MODE_CYCLING] else "--'--\"",
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
        
        response = requests.post(
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
            print(f"发送状态失败: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"通信错误: {e}")
        return False

def send_carbon():
    response = requests.get(
            f"{SERVER_URL}/api/carbon",
            timeout=5
        )
    if response.status_code == 200:
        print("发送减碳成功")

def change_mode_internal(new_mode):
    """内部模式切换（不触发按钮）"""
    global current_mode
    
    if message_showing:
        return
    
    old_mode = current_mode
    
    if old_mode == MODE_MEETING:
        exit_meeting_mode()
    
    stop_all_voice()
    current_mode = new_mode
    ui_elements['mode_back_line'].config(color=LINE_COLORS[current_mode])
    for t, x in enumerate(ui_elements['mode_text']):
        x.config(text=MODE_NAMES[current_mode][t], 
                                   color=MODE_COLORS[current_mode])
    add_voice(f"切换到{MODE_NAMES[current_mode]}")
    
    update_ui_mode()
    
    if current_mode == MODE_MEETING:
        enter_meeting_mode()

def handle_command(cmd):
    """处理服务器命令"""
    global current_mode, led_brightness
    
    command = cmd.get("command")
    
    if command == "change_mode":
        # 如果正在显示消息，先退出消息显示
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
    while running:
        send_status()
        time.sleep(UPDATE_INTERVAL)

# ==================== 主循环 ====================
def main_loop():
    """主循环"""
    while running:
        try:
            # 消息显示时不更新UI
            if not message_showing:
                if current_mode != MODE_MEETING:
                    ui_elements['time_text'].config(text=f"{datetime.now().strftime('%H:%M:%S')}")
                
                if not emergency_mode:
                    if current_mode == MODE_LIFE:
                        handle_life_mode()
                    elif current_mode == MODE_SPORT:
                        handle_sport_mode()
                    elif current_mode == MODE_CYCLING:
                        handle_cycling_mode()
                    elif current_mode == MODE_MEETING:
                        handle_meeting_mode()
                    
        except Exception as e:
            print(f"主循环错误: {e}")
            print(e.with_traceback)
        
        time.sleep(0.1)

# ==================== 启动程序 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("运动腿环系统启动")
    print("=" * 60)
    
    # 硬件初始化
    print("初始化硬件...")
    Board().begin()
    
    dht11 = DHT11(Pin(PIN_DHT11))
    print("DHT11初始化成功")
    button = Pin(PIN_BUTTON, Pin.IN)
    print("按钮初始化成功")
    knob = Pin(PIN_KNOB, Pin.ANALOG)
    print("旋钮初始化成功")
    led_strip = NeoPixel(Pin(PIN_LED), LED_COUNT)
    led_strip.brightness(led_brightness)
    print(f"LED初始化成功{led_strip}")
    
    tts = DFRobot_SpeechSynthesis_I2C()
    tts.begin(tts.V2)
    tts.set_voice(9)
    tts.set_speed(5)
    tts.set_tone(5)
    tts.set_sound_type(tts.FEMALE2)
    
    # 初始化GUI
    gui = GUI()
    init_ui()
    
    print("✓ 硬件初始化完成")
    print(f"姿态检测配置:")
    print(f"  检测轴: {POSTURE_AXIS.upper()}轴")
    print(f"  阈值: {POSTURE_THRESHOLD}")
    print(f"  坐姿方向: {'>' if SITTING_DIRECTION == 'greater' else '<'} {POSTURE_THRESHOLD}")
    print("=" * 60)
    
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
            print(f"✓ 启动线程: {t.name}")
        
        print("=" * 60)
        print("✓ 系统启动完成")
        print(f"✓ 服务器: {SERVER_URL}")
        print("=" * 60)
        
        add_voice("运动腿环系统已启动")
        
        while running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n程序中断")
    finally:
        exit_handler()