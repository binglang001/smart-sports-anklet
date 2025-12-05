# 项目结构说明

本文档详细说明运动腿环系统的文件组织结构。

## 目录树

```
smart-sports-anklet/
│
├── README.md                    # 项目主文档
├── QUICKSTART.md                # 快速开始指南
├── LICENSE                      # MIT开源许可证
├── requirements.txt             # Python依赖列表
│
├── server.py                  # Flask后端服务器（核心）
├── client.py                  # 行空板客户端程序（核心）
├── control.html                 # Web控制界面（核心）
│
├── start_server.bat             # Windows启动脚本
├── start_server.sh              # Linux/Mac启动脚本
│
└── data/                        # 数据存储目录（运行时自动创建）
    ├── emergency.json           # 紧急事件记录
    ├── history.json             # 历史运动数据
    ├── sport_records.json       # 运动记录详情
    └── settings.json            # 系统设置
```

---

## 核心文件说明

### 1. server.py

**功能**: Flask后端服务器主程序

**主要组件**:
- REST API端点
- 数据持久化管理
- 控制命令队列
- 设备状态管理
- 定时任务（离线检测）

**启动方式**:
```bash
python server.py
```

**监听端口**: 5000

### 2. client.py

**功能**: 行空板M10客户端程序

**主要组件**:
- 硬件控制（传感器、LED、按钮等）
- 姿态检测与运动追踪
- 语音播报
- UI显示管理
- 与服务器通信

**运行平台**: 行空板M10

**依赖库**:
- pinpong
- DFRobot_SpeechSynthesis
- unihiker

### 3. control.html

**功能**: Web控制界面

**特性**:
- 响应式设计（支持手机和桌面）
- 实时数据显示
- 模式切换控制
- 历史数据可视化
- 紧急记录管理

**访问方式**: `http://服务器IP:5000`

---

## 配置文件

### requirements.txt

Python依赖包列表，包含：
- Flask: Web框架
- Flask-CORS: 跨域支持
- requests: HTTP请求库
- 其他依赖

安装方式:
```bash
pip install -r requirements.txt
```

### .gitignore

Git版本控制忽略规则，防止提交：
- Python缓存文件 (`__pycache__`)
- 虚拟环境 (`venv/`)
- 数据文件 (`data/`)
- 日志文件 (`*.log`)
- IDE配置 (`.vscode/`, `.idea/`)

### config_example.py

配置示例文件，包含：
- 服务器配置
- 硬件引脚定义
- 传感器参数
- 运动检测阈值
- 提醒设置

使用方法：复制为 `config.py` 并修改。

---

## 数据文件

### data/emergency.json

紧急事件记录，格式：
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

### data/history.json

历史运动数据，按日期存储：
```json
{
  "2024-01-15": {
    "sport_time": 45,
    "activity_hours": [9, 10, 14],
    "carbon_reduce": 0.7392,
    "step": 5280
  }
}
```

### data/sport_records.json

详细运动记录：
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

### data/settings.json

系统设置：
```json
{
  "sitting_remind_duration": 3600
}
```

---

## 启动脚本

### start_server.bat (Windows)

Windows批处理脚本，功能：
- 检查Python环境
- 安装依赖
- 创建数据目录
- 启动服务器

### start_server.sh (Linux/Mac)

Shell脚本，功能与bat相同。

使用前需添加执行权限：
```bash
chmod +x start_server.sh
./start_server.sh
```

---

## 文档文件

### README.md

主文档，包含：
- 项目介绍
- 功能特性
- 安装部署
- 使用说明
- API文档

### QUICKSTART.md

5分钟快速入门指南，适合初次使用者。

### LICENSE

MIT开源许可证，允许：
- 商业使用
- 修改
- 分发
- 私人使用

---

## 数据存储位置

### 开发环境
```
./data/
```

### 生产环境（推荐）

**Linux**:
```
/var/lib/sports-anklet/data/
```

**Windows**:
```
C:\ProgramData\SportsAnklet\data\
```

**Mac**:
```
~/Library/Application Support/SportsAnklet/data/
```

---

## 版本历史

### v1.0.0 (当前)
- 初始版本
- 基础运动监测
- Web控制界面
- 数据持久化

---

## 维护建议

1. **定期备份data目录**
2. **查看日志文件排查问题**
3. **保持依赖包更新**
4. **定期清理旧数据**

---

## 文件许可

所有代码文件采用 MIT 许可证。
文档文件采用 CC BY 4.0 许可证。