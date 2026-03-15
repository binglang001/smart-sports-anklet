# -*- coding: UTF-8 -*-
"""
Flask服务器程序 - 运动腰带系统
提供REST API和Web界面
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import threading
import time
import os

# 数据保存调度器
last_save_time = 0
save_lock = threading.Lock()
SAVE_INTERVAL = 30  # 30秒保存一次

def atomic_save(filepath, data):
    """原子性保存：先写临时文件，再重命名"""
    temp_path = filepath + ".tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, filepath)
    except Exception as e:
        print(f"保存失败 {filepath}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def schedule_save():
    """定时保存调度器"""
    global last_save_time
    if time.time() - last_save_time > SAVE_INTERVAL:
        save_all_data()
        last_save_time = time.time()

def save_all_data():
    """保存所有数据"""
    with save_lock:
        try:
            atomic_save(HISTORY_FILE, sport_history)
            atomic_save(EMERGENCY_FILE, emergency_records)
            atomic_save(SPORT_RECORDS_FILE, sport_records)
            atomic_save(SETTINGS_FILE, {"sitting_remind_duration": sitting_remind_duration})
            print(f"[数据] 已保存")
        except Exception as e:
            print(f"[数据] 保存失败: {e}")

app = Flask(__name__)
CORS(app)

MODE_VALUES = (0, 1, 2)
CARBON_PER_STEP = 0.03

# 全局数据存储
device_status = {
    "mode": 0,
    "temperature": 25.0,
    "humidity": 50.0,
    "brightness": 100,
    "posture": "unknown",
    "pace": 0,
    "pace_str": "--'--\"",
    "step": 0,
    "carbon_reduce": 0,
    "emergency": False,
    "sport_time_today": 0,
    "activity_hours": [],
    "last_update": None,
    "online": False,
    "sitting_duration": 0,
    "sport_duration": 0,
    "message_showing": False
}

# 控制命令队列
control_commands = []
command_lock = threading.Lock()

# 紧急记录
emergency_records = []

# 历史运动数据
sport_history = {}

# 运动记录
sport_records = []

# 设备状态跟踪
device_last_step = 0  # 上次上报的步数
device_stats_date = datetime.now().strftime("%Y-%m-%d")

# 久坐提醒设置（秒）
sitting_remind_duration = 3600

# 数据文件路径
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EMERGENCY_FILE = os.path.join(DATA_DIR, "emergency.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SPORT_RECORDS_FILE = os.path.join(DATA_DIR, "sport_records.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 数据持久化 ====================
def rollover_daily_device_counters(now=None):
    """跨天时重置服务端维护的今日计数器"""
    global device_stats_date

    if now is None:
        now = datetime.now()

    today = now.strftime("%Y-%m-%d")
    if today != device_stats_date:
        device_status["step"] = 0
        device_status["carbon_reduce"] = 0
        device_stats_date = today


def load_data():
    """加载历史数据"""
    global emergency_records, sport_history, sport_records, sitting_remind_duration
    
    try:
        if os.path.exists(EMERGENCY_FILE):
            with open(EMERGENCY_FILE, 'r', encoding='utf-8') as f:
                emergency_records = json.load(f)
    except:
        emergency_records = []
    
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                sport_history = json.load(f)
    except:
        sport_history = {}
    
    try:
        if os.path.exists(SPORT_RECORDS_FILE):
            with open(SPORT_RECORDS_FILE, 'r', encoding='utf-8') as f:
                sport_records = json.load(f)
    except:
        sport_records = []
    
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                sitting_remind_duration = settings.get("sitting_remind_duration", 3600)
    except:
        sitting_remind_duration = 3600


def init_device_daily_counters_from_history(now=None):
    """服务端重启后，用已持久化的今日数据恢复计数器，避免回到0"""
    global device_last_step, device_stats_date

    if now is None:
        now = datetime.now()

    today = now.strftime("%Y-%m-%d")
    device_stats_date = today

    today_history = sport_history.get(today) if isinstance(sport_history, dict) else None
    if isinstance(today_history, dict):
        try:
            device_status["step"] = max(0, int(today_history.get("step", 0) or 0))
        except Exception:
            device_status["step"] = 0

        try:
            device_status["carbon_reduce"] = round(float(today_history.get("carbon_reduce", 0) or 0), 4)
        except Exception:
            device_status["carbon_reduce"] = 0

        device_last_step = device_status["step"]
    else:
        device_status["step"] = 0
        device_status["carbon_reduce"] = 0
        device_last_step = 0

def save_emergency():
    """保存紧急记录"""
    try:
        atomic_save(EMERGENCY_FILE, emergency_records)
    except Exception as e:
        print(f"保存紧急记录失败: {e}")

def save_history():
    """保存历史数据"""
    try:
        atomic_save(HISTORY_FILE, sport_history)
    except Exception as e:
        print(f"保存历史数据失败: {e}")

def save_sport_records():
    """保存运动记录"""
    try:
        atomic_save(SPORT_RECORDS_FILE, sport_records)
    except Exception as e:
        print(f"保存运动记录失败: {e}")

def save_settings():
    """保存设置"""
    try:
        settings = {"sitting_remind_duration": sitting_remind_duration}
        atomic_save(SETTINGS_FILE, settings)
    except Exception as e:
        print(f"保存设置失败: {e}")


def _safe_int(value, default=0):
    """安全转换为整数"""
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    """安全转换为浮点数"""
    try:
        return float(value)
    except Exception:
        return default


def _build_pace_str(duration_seconds, distance_km):
    """根据时长和距离生成配速字符串"""
    duration_seconds = _safe_float(duration_seconds, 0)
    distance_km = _safe_float(distance_km, 0)

    if duration_seconds <= 0 or distance_km <= 0:
        return None

    pace_min_per_km = (duration_seconds / 60.0) / distance_km
    if pace_min_per_km <= 0 or pace_min_per_km > 99:
        return None

    minutes = int(pace_min_per_km)
    seconds = int(round((pace_min_per_km - minutes) * 60))
    if seconds >= 60:
        minutes += 1
        seconds -= 60
    return f"{minutes}'{seconds:02d}\""


def normalize_sport_record(record):
    """标准化运动记录，兼容旧记录缺失字段的情况"""
    if not isinstance(record, dict):
        return record

    item = dict(record)
    series = item.get("series")

    distance_km = _safe_float(item.get("distance_km"), 0)
    distance_step_km = _safe_float(item.get("distance_step_km"), 0)
    distance_gnss_km = _safe_float(item.get("distance_gnss_km"), 0)
    distance_source = item.get("distance_source") if isinstance(item.get("distance_source"), str) else ""
    avg_stride_m = _safe_float(item.get("avg_stride_m"), 0)
    avg_cadence_spm = _safe_float(item.get("avg_cadence_spm"), 0)
    carbon_reduce = _safe_float(item.get("carbon_reduce"), 0)
    gnss_valid_ratio = _safe_float(item.get("gnss_valid_ratio"), 0)
    gnss_fix_samples = max(0, _safe_int(item.get("gnss_fix_samples"), 0))
    gnss_total_samples = max(0, _safe_int(item.get("gnss_total_samples"), 0))
    gnss_satellite_max = max(0, _safe_int(item.get("gnss_satellite_max"), 0))

    clean_gnss_track = []
    raw_gnss_track = item.get("gnss_track")
    if isinstance(raw_gnss_track, list):
        for point in raw_gnss_track:
            if not isinstance(point, dict):
                continue

            lat = _safe_float(point.get("lat"), None)
            lon = _safe_float(point.get("lon"), None)
            if lat is None or lon is None:
                continue
            if abs(lat) > 90 or abs(lon) > 180:
                continue

            clean_point = {
                "lat": round(lat, 7),
                "lon": round(lon, 7),
            }

            t = _safe_int(point.get("t"), None)
            if t is not None and t >= 0:
                clean_point["t"] = t

            point_distance_km = _safe_float(point.get("distance_km"), None)
            if point_distance_km is not None and point_distance_km >= 0:
                clean_point["distance_km"] = round(point_distance_km, 3)

            satellites = _safe_int(point.get("satellites"), None)
            if satellites is not None and satellites >= 0:
                clean_point["satellites"] = satellites

            speed_kmh = _safe_float(point.get("speed_kmh"), None)
            if speed_kmh is None:
                speed_kmh = _safe_float(point.get("gnss_speed_kmh"), None)
            if speed_kmh is not None and speed_kmh >= 0:
                clean_point["speed_kmh"] = round(speed_kmh, 2)

            heading_deg = _safe_float(point.get("heading_deg"), None)
            if heading_deg is not None:
                clean_point["heading_deg"] = round(heading_deg % 360, 1)

            utc = point.get("utc")
            if isinstance(utc, str) and utc:
                clean_point["utc"] = utc

            clean_gnss_track.append(clean_point)

    if clean_gnss_track:
        item["gnss_track"] = clean_gnss_track
        if distance_gnss_km <= 0:
            track_distances = [_safe_float(point.get("distance_km"), 0) for point in clean_gnss_track]
            valid_track_distances = [value for value in track_distances if value >= 0]
            if valid_track_distances:
                distance_gnss_km = round(max(valid_track_distances), 3)
    elif "gnss_track" in item:
        item["gnss_track"] = []

    if isinstance(series, list) and series:
        distance_points = [_safe_float(point.get("distance_km"), 0) for point in series if isinstance(point, dict)]
        stride_points = [_safe_float(point.get("stride_m"), 0) for point in series if isinstance(point, dict)]
        cadence_points = [_safe_float(point.get("cadence_spm"), 0) for point in series if isinstance(point, dict)]
        carbon_points = [_safe_float(point.get("carbon_reduce"), 0) for point in series if isinstance(point, dict)]

        valid_distances = [value for value in distance_points if value > 0]
        valid_strides = [value for value in stride_points if value > 0]
        valid_cadences = [value for value in cadence_points if value > 0]
        valid_carbons = [value for value in carbon_points if value >= 0]

        if distance_km <= 0 and valid_distances:
            distance_km = round(max(valid_distances), 3)

        if avg_stride_m <= 0 and valid_strides:
            avg_stride_m = round(sum(valid_strides) / len(valid_strides), 2)

        if avg_cadence_spm <= 0 and valid_cadences:
            avg_cadence_spm = round(sum(valid_cadences) / len(valid_cadences), 1)

        if carbon_reduce <= 0 and valid_carbons:
            carbon_reduce = round(max(valid_carbons), 2)

    steps = max(0, _safe_int(item.get("step"), 0))
    duration = max(0, _safe_float(item.get("duration"), 0))

    if distance_step_km <= 0 and distance_source != "gnss" and distance_km > 0:
        distance_step_km = round(distance_km, 3)
    if distance_source == "gnss" and distance_gnss_km <= 0 and distance_km > 0:
        distance_gnss_km = round(distance_km, 3)

    if distance_source == "gnss" and distance_gnss_km > 0:
        distance_km = distance_gnss_km
    elif distance_km <= 0:
        if distance_step_km > 0:
            distance_km = distance_step_km
        elif distance_gnss_km > 0:
            distance_km = distance_gnss_km
    if distance_km <= 0 and steps > 0 and avg_stride_m > 0:
        distance_km = round((steps * avg_stride_m) / 1000.0, 3)

    if avg_stride_m <= 0 and steps > 0 and distance_km > 0:
        avg_stride_m = round((distance_km * 1000.0) / steps, 2)

    if avg_cadence_spm <= 0 and steps > 0 and duration > 0:
        avg_cadence_spm = round((steps / duration) * 60.0, 1)

    if carbon_reduce <= 0 and steps > 0:
        carbon_reduce = round(steps * CARBON_PER_STEP, 2)

    if not item.get("pace"):
        item["pace"] = _build_pace_str(duration, distance_km) or "--'--\""

    gnss_valid_ratio = min(1.0, max(0.0, gnss_valid_ratio))
    if gnss_total_samples > 0 and gnss_fix_samples > gnss_total_samples:
        gnss_fix_samples = gnss_total_samples

    if distance_source not in ("step", "gnss"):
        distance_source = "gnss" if distance_gnss_km > 0 else "step"
    elif distance_source == "gnss" and distance_gnss_km <= 0 and distance_step_km > 0:
        distance_source = "step"

    if distance_km > 0:
        item["distance_km"] = distance_km
    if distance_step_km > 0:
        item["distance_step_km"] = distance_step_km
    if distance_gnss_km > 0:
        item["distance_gnss_km"] = distance_gnss_km
    if avg_stride_m > 0:
        item["avg_stride_m"] = avg_stride_m
    if avg_cadence_spm > 0:
        item["avg_cadence_spm"] = avg_cadence_spm
    item["distance_source"] = distance_source
    item["carbon_reduce"] = round(max(0, carbon_reduce), 2)
    item["gnss_valid_ratio"] = gnss_valid_ratio
    item["gnss_fix_samples"] = gnss_fix_samples
    item["gnss_total_samples"] = gnss_total_samples
    item["gnss_satellite_max"] = gnss_satellite_max

    return item

# ==================== API端点 ====================

@app.route('/')
def index():
    """返回控制页面"""
    return send_from_directory(os.path.dirname(__file__), 'control.html')

@app.route('/history')
def history_page():
    """历史统计页面"""
    return send_from_directory(os.path.dirname(__file__), 'history.html')

@app.route('/sport_record_detail')
def sport_record_detail_page():
    """运动记录详情页面"""
    return send_from_directory(os.path.dirname(__file__), 'sport_record_detail.html')

@app.route('/api/status', methods=['POST'])
def update_status():
    """接收设备状态更新"""
    global device_status, sport_history, device_last_step

    try:
        data = request.json or {}
        current_time = datetime.now()
        rollover_daily_device_counters(current_time)

        current_mode = data.get("mode", 0)
        if current_mode not in MODE_VALUES:
            return jsonify({"status": "error", "message": "无效模式值"}), 400

        # 获取当前步数
        current_step = max(0, int(data.get("step", 0) or 0))

        # 计算步数增量
        if current_step >= device_last_step:
            step_increment = current_step - device_last_step
        else:
            step_increment = current_step

        # 计算碳排放增量（仅在运动模式）
        carbon_increment = 0

        # 只有在运动模式(MODE_SPORT=1)时才累加碳排放
        if current_mode == 1 and step_increment > 0:
            carbon_increment = step_increment * CARBON_PER_STEP
            device_status["carbon_reduce"] = round(
                device_status["carbon_reduce"] + carbon_increment, 4
            )

        # 更新步数记录
        device_last_step = current_step

        # 更新设备状态
        device_status.update({
            "mode": current_mode,
            "temperature": data.get("temperature", device_status["temperature"]),
            "humidity": data.get("humidity", device_status["humidity"]),
            "brightness": data.get("brightness", device_status["brightness"]),
            "posture": data.get("posture", device_status["posture"]),
            "pace": data.get("pace", device_status["pace"]),
            "pace_str": data.get("pace_str", device_status["pace_str"]),
            "step": device_status["step"] + step_increment,
            "carbon_reduce": device_status["carbon_reduce"],
            "emergency": data.get("emergency", device_status["emergency"]),
            "sport_time_today": data.get("sport_time_today", device_status["sport_time_today"]),
            "activity_hours": data.get("activity_hours", device_status["activity_hours"]),
            "sitting_duration": data.get("sitting_duration", device_status["sitting_duration"]),
            "sport_duration": data.get("sport_duration", device_status["sport_duration"]),
            "message_showing": data.get("message_showing", device_status["message_showing"]),
            "last_update": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "online": True
        })

        # 更新今日历史数据
        today = current_time.strftime("%Y-%m-%d")
        if today not in sport_history:
            sport_history[today] = {
                "sport_time": 0,
                "activity_hours": [],
                "step": 0,
                "carbon_reduce": 0
            }

        sport_history[today]["sport_time"] = device_status["sport_time_today"]
        sport_history[today]["activity_hours"] = device_status["activity_hours"]
        sport_history[today]["carbon_reduce"] = device_status["carbon_reduce"]
        sport_history[today]["step"] = device_status["step"]

        # 定期保存历史数据（使用新的调度器）
        schedule_save()

        # 处理紧急情况
        if data.get("emergency") and not device_status.get("emergency_recorded"):
            emergency_records.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": "检测到摔倒，需要紧急救助",
                "location": "未知",
                "resolved": False
            })
            save_emergency()
            device_status["emergency_recorded"] = True
        elif not data.get("emergency"):
            device_status["emergency_recorded"] = False
        
        # 返回待执行的命令
        with command_lock:
            commands = control_commands.copy()
            control_commands.clear()
        
        return jsonify({
            "status": "ok",
            "commands": commands,
            "sitting_remind_duration": sitting_remind_duration
        })
        
    except Exception as e:
        print(f"更新状态错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """获取设备状态"""
    rollover_daily_device_counters()

    carbon_from_history = 0
    days = request.args.get('days', type=int)
    today = datetime.now()

    if days and days > 0:
        for i in range(days):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            if date in sport_history:
                carbon_from_history += sport_history[date].get("carbon_reduce", 0)
    else:
        for history in sport_history.values():
            carbon_from_history += history.get("carbon_reduce", 0)

    # 设备在线检测
    if device_status["last_update"]:
        try:
            last_time = datetime.strptime(device_status["last_update"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_time > timedelta(seconds=10):
                device_status["online"] = False
        except:
            device_status["online"] = False

    device_status['carbon_reduce_all'] = round(carbon_from_history, 4)

    return jsonify(device_status)

@app.route('/api/control', methods=['POST'])
def send_control():
    """发送控制命令"""
    try:
        data = request.json or {}
        command = data.get("command")

        if command == "change_mode" and data.get("mode") not in MODE_VALUES:
            return jsonify({"status": "error", "message": "无效模式值"}), 400
        
        with command_lock:
            control_commands.append(data)
        
        print(f"收到控制命令: {command}")
        return jsonify({"status": "ok"})
        
    except Exception as e:
        print(f"发送控制命令错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/emergency', methods=['GET'])
def get_emergency_records():
    """获取紧急记录"""
    return jsonify(emergency_records)

@app.route('/api/emergency/<int:index>', methods=['PUT'])
def resolve_emergency(index):
    """标记紧急情况已解决"""
    try:
        if 0 <= index < len(emergency_records):
            emergency_records[index]["resolved"] = True
            save_emergency()
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "message": "记录不存在"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史数据"""
    days = request.args.get('days', 7, type=int)
    all_records = request.args.get('all', 0, type=int)

    result = {}
    today = datetime.now()

    if all_records:
        for date in sorted(sport_history.keys()):
            result[date] = sport_history.get(date, {
                "sport_time": 0,
                "activity_hours": [],
                "step": 0,
                "carbon_reduce": 0,
            })
        return jsonify(result)

    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if date in sport_history:
            result[date] = sport_history[date]
        else:
            result[date] = {
                "sport_time": 0,
                "activity_hours": [],
                "step": 0,
                "carbon_reduce": 0,
            }

    return jsonify(result)

@app.route('/api/message', methods=['POST'])
def send_message():
    """向设备发送消息"""
    try:
        data = request.json
        message = data.get("message", "")
        
        with command_lock:
            control_commands.append({
                "command": "message",
                "content": message
            })
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sport_records', methods=['GET'])
def get_sport_records():
    """获取运动记录"""
    include_series = request.args.get('include_series', 0, type=int)
    limit = request.args.get('limit', type=int)
    reverse = request.args.get('reverse', 0, type=int)

    indexed_records = list(enumerate(sport_records))
    if reverse:
        indexed_records = indexed_records[::-1]

    if limit and limit > 0:
        indexed_records = indexed_records[:limit] if reverse else indexed_records[-limit:]

    result = []
    for idx, record in indexed_records:
        if not isinstance(record, dict):
            result.append({"_index": idx, "data": record})
            continue

        item = normalize_sport_record(record)
        item["_index"] = idx
        if not include_series:
            item.pop("series", None)
            item.pop("gnss_track", None)
        result.append(item)

    return jsonify(result)


@app.route('/api/sport_records/<int:record_index>', methods=['GET'])
def get_sport_record(record_index):
    """获取单条运动记录"""
    include_series = request.args.get('include_series', 1, type=int)

    if record_index < 0 or record_index >= len(sport_records):
        return jsonify({"status": "error", "message": "记录不存在"}), 404

    record = sport_records[record_index]
    if not isinstance(record, dict):
        return jsonify(record)

    item = normalize_sport_record(record)
    item["_index"] = record_index
    if not include_series:
        item.pop("series", None)
        item.pop("gnss_track", None)
    return jsonify(item)

@app.route('/api/sport_records', methods=['POST'])
def add_sport_record():
    """添加运动记录"""
    try:
        data = request.json or {}
        if not data:
            return jsonify({"status": "error", "message": "数据为空"}), 400
        sport_records.append(normalize_sport_record(data))
        save_sport_records()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/sync_records', methods=['POST'])
def sync_records():
    """批量同步运动记录（离线模式切换到在线时使用）"""
    try:
        data = request.json or {}
        records = data.get("records", [])

        if not records:
            return jsonify({"status": "ok", "synced_count": 0})

        synced_count = 0
        for record in records:
            sport_records.append(normalize_sport_record(record))
            synced_count += 1

        save_sport_records()
        print(f"[同步] 批量接收 {synced_count} 条运动记录")

        return jsonify({
            "status": "ok",
            "synced_count": synced_count
        })
    except Exception as e:
        print(f"批量同步错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/sync_emergency', methods=['POST'])
def sync_emergency():
    """批量同步紧急记录"""
    try:
        data = request.json
        records = data.get("records", [])

        if not records:
            return jsonify({"status": "ok", "synced_count": 0})

        synced_count = 0
        for record in records:
            emergency_records.append(record)
            synced_count += 1

        save_emergency()
        print(f"[同步] 批量接收 {synced_count} 条紧急记录")

        return jsonify({
            "status": "ok",
            "synced_count": synced_count
        })
    except Exception as e:
        print(f"批量同步错误: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取设置"""
    return jsonify({"sitting_remind_duration": sitting_remind_duration})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """更新设置"""
    global sitting_remind_duration
    try:
        data = request.json or {}
        new_duration = int(data.get("sitting_remind_duration", sitting_remind_duration))
        if new_duration < 60:
            return jsonify({"status": "error", "message": "提醒时长不能小于60秒"}), 400

        sitting_remind_duration = new_duration
        save_settings()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==================== 启动服务 ====================
def check_offline():
    """定期检查设备在线状态"""
    while True:
        time.sleep(5)
        if device_status["last_update"]:
            try:
                last_time = datetime.strptime(device_status["last_update"], "%Y-%m-%d %H:%M:%S")
                if datetime.now() - last_time > timedelta(seconds=10):
                    if device_status["online"]:
                        device_status["online"] = False
                        print("设备已离线")
            except:
                pass

if __name__ == "__main__":
    print("=" * 50)
    print("运动腰带Flask服务器")
    print("=" * 50)
    
    load_data()
    init_device_daily_counters_from_history()
    print(f"✓ 加载历史数据: {len(emergency_records)}条紧急记录")
    print(f"✓ 加载运动记录: {len(sport_records)}条")
    
    offline_thread = threading.Thread(target=check_offline, daemon=True)
    offline_thread.start()
    
    print("✓ 服务器启动在 http://0.0.0.0:5000")
    print("✓ 控制页面: http://localhost:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
