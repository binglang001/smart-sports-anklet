#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Flask服务器程序 - 运动腿环系统
提供REST API和Web界面
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import threading
import time
import os

app = Flask(__name__)
CORS(app)

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

carbon_reduce_all = 0

# 久坐提醒设置（秒）
sitting_remind_duration = 3600

# 数据文件路径
DATA_DIR = "data"
EMERGENCY_FILE = os.path.join(DATA_DIR, "emergency.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SPORT_RECORDS_FILE = os.path.join(DATA_DIR, "sport_records.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 数据持久化 ====================
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

def save_emergency():
    """保存紧急记录"""
    try:
        with open(EMERGENCY_FILE, 'w', encoding='utf-8') as f:
            json.dump(emergency_records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存紧急记录失败: {e}")

def save_history():
    """保存历史数据"""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(sport_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存历史数据失败: {e}")

def save_sport_records():
    """保存运动记录"""
    try:
        with open(SPORT_RECORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sport_records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存运动记录失败: {e}")

def save_settings():
    """保存设置"""
    try:
        settings = {"sitting_remind_duration": sitting_remind_duration}
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存设置失败: {e}")

# ==================== API端点 ====================

@app.route('/')
def index():
    """返回控制页面"""
    return send_from_directory('.', 'control.html')

@app.route('/api/status', methods=['POST'])
def update_status():
    """接收设备状态更新"""
    global device_status, sport_history, carbon_reduce_all
    
    try:
        data = request.json
        
        # 更新设备状态
        device_status.update({
            "mode": data.get("mode", device_status["mode"]),
            "temperature": data.get("temperature", device_status["temperature"]),
            "humidity": data.get("humidity", device_status["humidity"]),
            "brightness": data.get("brightness", device_status["brightness"]),
            "posture": data.get("posture", device_status["posture"]),
            "pace": data.get("pace", device_status["pace"]),
            "pace_str": data.get("pace_str", device_status["pace_str"]),
            "step": data.get("step", device_status["step"]),
            "carbon_reduce": round(data.get("carbon_reduce", device_status["carbon_reduce"]), 4),
            "emergency": data.get("emergency", device_status["emergency"]),
            "sport_time_today": data.get("sport_time_today", device_status["sport_time_today"]),
            "activity_hours": data.get("activity_hours", device_status["activity_hours"]),
            "sitting_duration": data.get("sitting_duration", device_status["sitting_duration"]),
            "sport_duration": data.get("sport_duration", device_status["sport_duration"]),
            "message_showing": data.get("message_showing", device_status["message_showing"]),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "online": True
        })
        
        # 更新今日历史数据
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in sport_history:
            sport_history[today] = {"sport_time": 0, "activity_hours": []}
        
        sport_history[today]["sport_time"] = device_status["sport_time_today"]
        sport_history[today]["activity_hours"] = device_status["activity_hours"]
        sport_history[today]["carbon_reduce"] = device_status["carbon_reduce"]
        sport_history[today]["step"] = device_status["step"]
        
        # 定期保存历史数据
        if int(time.time()) % 60 == 0:
            save_history()
        
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
    global carbon_reduce_all
    carbon_reduce_history = 0

    days = request.args.get('days', 7, type=int)
    today = datetime.now()
    
    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if date in sport_history:
            carbon_reduce_history += sport_history[date]["carbon_reduce"]
    if device_status["last_update"]:
        last_time = datetime.strptime(device_status["last_update"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - last_time > timedelta(seconds=10):
            device_status["online"] = False
    
    device_status['carbon_reduce_all'] = round(carbon_reduce_all + carbon_reduce_history, 4)
    
    return jsonify(device_status)

@app.route('/api/control', methods=['POST'])
def send_control():
    """发送控制命令"""
    try:
        data = request.json
        command = data.get("command")
        
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

@app.route('/api/carbon', methods=['GET'])
def add_carbon():
    """增加累计减碳"""
    global carbon_reduce_all
    carbon_reduce_all += 0.0014
    return jsonify({"status": "ok"})

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
    
    result = {}
    today = datetime.now()
    
    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if date in sport_history:
            result[date] = sport_history[date]
        else:
            result[date] = {"sport_time": 0, "activity_hours": []}
    
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
    return jsonify(sport_records)

@app.route('/api/sport_records', methods=['POST'])
def add_sport_record():
    """添加运动记录"""
    try:
        data = request.json
        sport_records.append(data)
        save_sport_records()
        return jsonify({"status": "ok"})
    except Exception as e:
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
        data = request.json
        sitting_remind_duration = data.get("sitting_remind_duration", sitting_remind_duration)
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
    print("运动腿环Flask服务器")
    print("=" * 50)
    
    load_data()
    print(f"✓ 加载历史数据: {len(emergency_records)}条紧急记录")
    print(f"✓ 加载运动记录: {len(sport_records)}条")
    
    offline_thread = threading.Thread(target=check_offline, daemon=True)
    offline_thread.start()
    
    print("✓ 服务器启动在 http://0.0.0.0:5000")
    print("✓ 控制页面: http://localhost:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)