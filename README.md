# 运动腿环系统 (Smart Sports Anklet System)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

一个基于行空板M10的智能运动腿环系统，支持多种运动模式监测、健康数据追踪和远程控制。

[功能特性](#功能特性) • [快速开始](#快速开始) • [部署教程](#部署教程) • [使用说明](#使用说明) • [API文档](#api文档)

</div>

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [硬件需求](#硬件需求)
- [快速开始](#快速开始)
- [部署教程](#部署教程)
- [使用说明](#使用说明)
- [API文档](#api文档)
- [故障排查](#故障排查)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

运动腿环系统是一个集成了多种传感器的智能可穿戴设备监控系统，通过行空板M10硬件平台实现实时数据采集、健康监测和运动追踪功能。系统采用前后端分离架构，提供Web控制界面和RESTful API接口。

### 主要功能

- **多模式运动监测**：生活、运动、骑行、会议四种模式
- **实时数据采集**：温度、湿度、姿态、步数等
- **健康提醒**：久坐提醒、运动建议、跌倒检测
- **碳减排统计**：运动减碳量计算和累计
- **远程控制**：Web界面实时监控和控制
- **数据持久化**：历史数据存储和分析
- **语音播报**：实时语音反馈和提醒
- **紧急救援**：跌倒检测和紧急通知

---

## 功能特性

### 1. 运动模式管理

#### 生活模式 (MODE_LIFE)
- 姿态监测（坐姿/站姿）
- 久坐时长统计和提醒
- 跌倒检测和紧急报警
- 环境温湿度监测

#### 运动模式 (MODE_SPORT)
- 实时步数统计
- 配速计算（分钟/公里）
- 运动时长记录
- 碳减排量估算
- 卡路里消耗计算

#### 骑行模式 (MODE_CYCLING)
- 骑行速度监测
- 里程统计
- 配速显示
- 环境数据记录

#### 会议模式 (MODE_MEETING)
- 屏幕黑屏节能
- 静音模式
- 仅保持数据采集

### 2. 数据监测

| 传感器类型 | 监测内容 | 更新频率 |
|-----------|---------|---------|
| DHT11 | 温度、湿度 | 5秒 |
| 加速度计 | 姿态、运动状态 | 实时 |
| 步数传感器 | 步数统计 | 实时 |
| 按钮 | 模式切换 | 实时 |
| 旋钮 | LED亮度调节 | 100ms |

### 3. Web控制界面

- **响应式设计**：自适应手机和桌面端
- **实时仪表盘**：设备状态、环境数据、运动统计
- **历史数据可视化**：7天/30天运动趋势图
- **远程控制**：模式切换、亮度调节、消息推送
- **紧急记录**：跌倒事件查看和处理
- **设置管理**：久坐提醒时长自定义

### 4. 数据持久化

```
data/
├── emergency.json        # 紧急事件记录
├── history.json          # 历史运动数据
├── sport_records.json    # 运动记录详情
└── settings.json         # 系统设置
```

### 5. API接口

完整的RESTful API支持，详见[API文档](#api文档)部分。

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                     Web Browser                      │
│              (control.html - 控制界面)               │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP/REST API
                   ▼
┌─────────────────────────────────────────────────────┐
│              Flask Server (server.py)             │
│  ┌──────────────────────────────────────────────┐  │
│  │  REST API Endpoints                           │  │
│  │  - /api/status   - /api/control               │  │
│  │  - /api/history  - /api/emergency             │  │
│  └──────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────┐  │
│  │  Data Storage                                 │  │
│  │  - JSON Files  - Command Queue                │  │
│  └──────────────────────────────────────────────┘  │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP Polling (2s interval)
                   ▼
┌─────────────────────────────────────────────────────┐
│        行空板M10 Client (client.py)                │
│  ┌──────────────────────────────────────────────┐  │
│  │  Hardware Control                             │  │
│  │  - DHT11  - LED Strip  - Button  - Knob      │  │
│  └──────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────┐  │
│  │  Data Processing                              │  │
│  │  - Posture Detection  - Step Counting         │  │
│  │  - Pace Calculation   - Carbon Tracking       │  │
│  └──────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────┐  │
│  │  UI & Voice                                   │  │
│  │  - OLED Display  - TTS Voice Synthesis        │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 硬件需求

### 必需硬件

| 硬件 | 型号 | 用途 |
|-----|------|-----|
| 主控板 | 行空板M10 | 主控制器 |
| 温湿度传感器 | DHT11 | 环境监测 |
| LED灯带 | WS2812 (7灯) | 状态指示 |
| 按钮 | 普通按钮 | 模式切换 |
| 旋钮 | 模拟旋钮 | 亮度调节 |
| 语音合成模块 | DFRobot语音合成 | 语音播报 |

### 引脚连接

```
DHT11      → P23
Button     → P24
Knob       → P22 (模拟)
LED Strip  → P21
```

### 软件环境

- **客户端（行空板M10）**
  - Python 3.7+
  - MindPlus/行空板开发环境
  
- **服务器**
  - Python 3.7+
  - Flask 2.0+
  - 任何支持Python的操作系统

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/binglang001/smart-sports-anklet.git
cd smart-sports-anklet
```

### 2. 安装服务器依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务器

```bash
python server.py
```

服务器将在 `http://0.0.0.0:5000` 启动。

### 4. 配置客户端

编辑 `client.py` 中的服务器地址：

```python
SERVER_URL = "http://YOUR_SERVER_IP:5000"  # 改为运行服务端的设备的IP
```

### 5. 部署到行空板

将 `client.py` 上传到行空板M10并运行。

### 6. 连接同一网络

将行空板与服务器连接到同一网络

### 7. 访问控制界面

服务器上浏览器打开：`http://localhost:5000`

---

## 部署教程

### 服务器部署（详细步骤）

#### Windows部署

1. **安装Python**
   ```bash
   # 下载Python 3.7+
   # 从 https://www.python.org/downloads/ 下载并安装
   ```

2. **创建项目目录**
   ```bash
   mkdir smart-sports-anklet
   cd smart-sports-anklet
   ```

3. **下载项目文件**
   ```bash
   # 将 server.py, control.html, requirements.txt 放入目录
   ```

4. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

5. **启动服务器**
   ```bash
   python server.py
   ```

6. **验证安装**
   - 浏览器访问 `http://localhost:5000`
   - 应该看到控制界面

#### Linux/树莓派部署

1. **更新系统**
   ```bash
   sudo apt-get update
   sudo apt-get upgrade
   ```

2. **安装Python和pip**
   ```bash
   sudo apt-get install python3 python3-pip
   ```

3. **克隆或下载项目**
   ```bash
   git clone https://github.com/binglang001/smart-sports-anklet.git
   cd smart-sports-anklet
   ```

4. **安装依赖**
   ```bash
   pip3 install -r requirements.txt
   ```

5. **后台运行服务器**
   ```bash
   nohup python3 server.py > server.log 2>&1 &
   ```

6. **设置开机自启动**（可选）
   ```bash
   # 创建systemd服务
   sudo nano /etc/systemd/system/sports-anklet.service
   ```
   
   添加以下内容：
   ```ini
   [Unit]
   Description=Smart Sports Anklet Server
   After=network.target
   
   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/smart-sports-anklet
   ExecStart=/usr/bin/python3 /home/pi/smart-sports-anklet/server.py
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   启用服务：
   ```bash
   sudo systemctl enable sports-anklet.service
   sudo systemctl start sports-anklet.service
   sudo systemctl status sports-anklet.service
   ```

### 客户端部署（行空板M10）

1. **连接硬件**
   - 按照[引脚连接](#引脚连接)图连接所有传感器

2. **安装行空板开发环境**
   - 下载MindPlus

3. **配置服务器地址**
   
   编辑 `client.py` 第20行：
   ```python
   SERVER_URL = "http://192.168.1.100:5000"  # 改为你的服务器IP
   ```

4. **配置姿态检测参数**（根据实际佩戴调整）
   
   ```python
   POSTURE_AXIS = "x"              # 检测轴：x, y, 或 z
   POSTURE_THRESHOLD = 0.49        # 阈值
   SITTING_DIRECTION = "less"      # 方向：less 或 greater
   ```

5. **上传代码**
   - 使用MindPlus或其他工具上传 `client.py` 到行空板
   - 确保所有依赖库已安装

6. **运行程序**
   ```bash
   python client.py
   ```

7. **验证连接**
   - 行空板屏幕应显示"运动腿环系统"
   - Web界面应显示"在线"状态
   - 语音应播报"运动腿环系统已启动"

### 网络配置

#### 同一局域网部署

1. 服务器和行空板连接同一WiFi
2. 查看服务器IP：
   - Windows: `ipconfig`
   - Linux: `ifconfig` 或 `ip addr`
3. 在客户端配置此IP地址

#### 远程访问部署

1. **使用内网穿透（推荐新手）**
   - 使用 frp、ngrok 等工具
   - 示例使用ngrok：
   ```bash
   ngrok http 5000
   ```
   - 使用生成的URL配置客户端

2. **配置端口转发（需要路由器权限）**
   - 在路由器管理界面配置端口转发
   - 转发外网端口到服务器的5000端口
   - 使用公网IP访问

---

## 使用说明

### 模式切换

**硬件操作：**
- **短按按钮**：切换到下一个模式
- **长按按钮**（1.5秒）：进入/退出紧急模式

**Web操作：**
- 点击界面上的模式滑块切换模式

### 姿态监测

系统自动检测用户姿态：
- **坐姿**：持续坐姿超过设定时间会语音提醒
- **站姿**：正常站立状态
- **运动中**：检测到运动时自动记录
- **跌倒**：触发紧急警报

### 运动数据

**步数统计：**
- 基于加速度计数据的步态识别
- 自动过滤无效震动

**配速计算：**
- 公式：配速 = 运动时长(分钟) / (步数 × 0.0007 公里)
- 实时显示在屏幕上

**减碳量：**
- 步行：0.14g CO₂/步
- 自动累计并同步到服务器

### 久坐提醒

1. **默认设置**：60分钟
2. **自定义设置**：
   - Web界面 → 设置按钮 → 修改久坐提醒时长
   - 保存后立即生效
3. **提醒方式**：
   - 语音播报："您已久坐XX分钟，建议起身活动"
   - 屏幕显示进度条

### 消息推送

从Web界面发送消息到设备：
1. 点击"发送消息"按钮
2. 输入消息内容
3. 设备将显示滚动消息并语音播报

### 数据查看

**实时数据：**
- 设备状态、环境数据、运动统计
- 刷新频率：2秒

**历史数据：**
- 点击"历史数据"标签
- 查看7天或自定义天数的运动趋势
- 图表显示运动时长、活跃小时数

**运动记录：**
- 每次运动结束自动保存记录
- 包含：日期、模式、时长、配速等

---

## API文档

### 基本信息

- **Base URL**: `http://your-server:5000`
- **Content-Type**: `application/json`

### 端点列表

#### 1. 获取设备状态

```http
GET /api/status
```

**查询参数：**
- `days` (可选): 获取历史数据天数，默认7

**响应示例：**
```json
{
  "mode": 0,
  "temperature": 25.3,
  "humidity": 55.2,
  "brightness": 128,
  "posture": "sitting",
  "pace": 0,
  "pace_str": "6'30\"",
  "step": 5280,
  "carbon_reduce": 0.7392,
  "emergency": false,
  "sport_time_today": 45,
  "activity_hours": [9, 10, 14, 15],
  "sitting_duration": 3600,
  "sport_duration": 2700,
  "message_showing": false,
  "last_update": "2024-01-15 14:30:25",
  "online": true,
  "carbon_reduce_all": 15.4821
}
```

#### 2. 更新设备状态

```http
POST /api/status
```

**请求体：**
```json
{
  "mode": 1,
  "temperature": 25.0,
  "humidity": 50.0,
  "brightness": 100,
  "posture": "standing",
  "pace": 0,
  "pace_str": "--'--\"",
  "step": 0,
  "carbon_reduce": 0.0,
  "emergency": false,
  "sport_time_today": 0,
  "activity_hours": [],
  "sitting_duration": 0,
  "sport_duration": 0,
  "message_showing": false
}
```

**响应：**
```json
{
  "status": "ok",
  "commands": [],
  "sitting_remind_duration": 3600
}
```

#### 3. 发送控制命令

```http
POST /api/control
```

**请求体示例：**

模式切换：
```json
{
  "command": "change_mode",
  "mode": 1
}
```

亮度调节：
```json
{
  "command": "set_brightness",
  "value": 200
}
```

#### 4. 发送消息

```http
POST /api/message
```

**请求体：**
```json
{
  "message": "记得补充水分！"
}
```

#### 5. 获取紧急记录

```http
GET /api/emergency
```

**响应示例：**
```json
[
  {
    "time": "2024-01-15 12:30:45",
    "message": "检测到摔倒，需要紧急救助",
    "location": "未知",
    "resolved": false
  }
]
```

#### 6. 标记紧急情况已解决

```http
PUT /api/emergency/<index>
```

**响应：**
```json
{
  "status": "ok"
}
```

#### 7. 获取历史数据

```http
GET /api/history?days=7
```

**响应示例：**
```json
{
  "2024-01-15": {
    "sport_time": 45,
    "activity_hours": [9, 10, 14],
    "carbon_reduce": 0.7392,
    "step": 5280
  },
  "2025-01-14": {
    "sport_time": 30,
    "activity_hours": [15, 16],
    "carbon_reduce": 0.4928,
    "step": 3520
  }
}
```

#### 8. 获取运动记录

```http
GET /api/sport_records
```

**响应示例：**
```json
[
  {
    "time": "2024-01-15 14:30:00",
    "mode": "运动模式",
    "duration": 2700,
    "pace": "6'30\"",
    "steps": 5280,
    "carbon_reduce": 0.7392
  }
]
```

#### 9. 添加运动记录

```http
POST /api/sport_records
```

**请求体：**
```json
{
  "time": "2024-01-15 14:30:00",
  "mode": "运动模式",
  "duration": 2700,
  "pace": "6'30\"",
  "steps": 5280,
  "carbon_reduce": 0.7392
}
```

#### 10. 获取设置

```http
GET /api/settings
```

**响应：**
```json
{
  "sitting_remind_duration": 3600
}
```

#### 11. 更新设置

```http
POST /api/settings
```

**请求体：**
```json
{
  "sitting_remind_duration": 7200
}
```

---

## 故障排查

### 常见问题

#### 1. 设备显示离线

**可能原因：**
- 网络连接问题
- 服务器地址配置错误
- 服务器未启动

**解决方案：**
```bash
# 检查服务器是否运行
curl http://localhost:5000/api/status

# 检查行空板网络
# 在行空板上ping服务器IP

# 检查防火墙设置
# Windows: 允许5000端口通过防火墙
# Linux: sudo ufw allow 5000
```

#### 2. 温湿度显示异常

**可能原因：**
- DHT11传感器连接松动
- 传感器故障

**解决方案：**
- 检查P23引脚连接
- 更换传感器测试
- 查看串口输出日志

#### 3. 步数统计不准确

**可能原因：**
- 加速度计灵敏度设置不当
- 设备佩戴位置不正确

**解决方案：**
- 调整步数检测阈值
- 确保设备稳定佩戴在脚踝

#### 4. 语音播报无声音

**可能原因：**
- TTS模块未正确初始化
- I2C连接问题

**解决方案：**
```python
# 检查TTS初始化代码
# 确认语音模块I2C地址
# 检查音量设置
```

#### 5. Web界面无法访问

**可能原因：**
- 服务器未启动
- 端口被占用
- 防火墙阻止

**解决方案：**
```bash
# 检查端口占用
netstat -an | grep 5000

# 更改端口
# 在server.py最后一行修改port参数

# 关闭防火墙测试
# Windows: 控制面板 → 防火墙
# Linux: sudo ufw disable
```

### 调试模式

启用详细日志：

```python
# server.py 最后一行
app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
```

查看客户端日志：
```bash
# 行空板串口监视器查看实时日志
```

---

## 项目结构

```
smart-sports-anklet/
├── README.md                 # 项目文档
├── requirements.txt          # Python依赖
├── LICENSE                  # 开源许可证
├── server.py              # Flask后端服务器
├── client.py              # 行空板客户端程序
├── control.html             # Web控制界面
└── data/                    # 数据目录（自动创建）
    ├── emergency.json       # 紧急记录
    ├── history.json         # 历史数据
    ├── sport_records.json   # 运动记录
    └── settings.json        # 系统设置
```

---

## 贡献指南

我们欢迎所有形式的贡献！

### 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 代码规范

- 遵循 PEP 8 Python代码规范
- 添加必要的注释和文档字符串
- 确保代码通过测试

### 报告问题

如果发现Bug或有功能建议，请[创建Issue](https://github.com/binglang001/smart-sports-anklet/issues)。

---

## 开发路线图

- [x] 基础运动监测功能
- [x] Web控制界面
- [x] 数据持久化存储
- [x] 跌倒检测和紧急警报
- [ ] 移动端APP
- [ ] 数据云同步
- [ ] AI运动建议
- [ ] 多设备支持
- [ ] 数据导出功能
- [ ] 社交分享功能

---

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 致谢

- 感谢[DFRobot](https://www.dfrobot.com/)提供的硬件支持
- 感谢所有贡献者的付出

---

## 联系方式

- 项目主页：[https://github.com/binglang001/smart-sports-anklet](https://github.com/binglang001/smart-sports-anklet)
- 问题反馈：[Issues](https://github.com/binglang001/smart-sports-anklet/issues)
- 邮箱：lianbingyu_v2@163.com

---

<div align="center">

**如果这个项目对你有帮助，请给我们一个 ⭐️**

Made with ❤️ by [binglang001]

</div>
