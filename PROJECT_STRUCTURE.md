# 项目结构说明

本文档用于说明当前仓库的主要目录、关键模块职责以及运行时数据的存放位置，便于后续维护、联调和二次开发。

## 目录树

```text
smart-sports-belt/
├─ client/                         # 设备端程序（行空板 M10）
│  ├─ main.py                      # 客户端主入口，集中管理模式、线程与状态
│  ├─ config.py                    # 设备端配置项
│  ├─ sensors/                     # 传感器访问与核心算法
│  │  ├─ icm20689.py               # ICM20689 访问
│  │  ├─ attitude.py               # 姿态角计算
│  │  ├─ gravity_remover.py        # 重力去除
│  │  ├─ step_detector.py          # 步数检测
│  │  ├─ posture_detector.py       # 姿态识别
│  │  ├─ fall_detector.py          # 跌倒检测
│  │  └─ high_freq_sampler.py      # 高频采样器
│  ├─ services/                    # 设备端服务模块
│  │  ├─ gnss_manager.py           # GNSS 驱动封装与轨迹能力
│  │  └─ offline_manager.py        # 离线缓存与恢复同步
│  ├─ ui/                          # 屏幕与模式显示逻辑
│  │  ├─ message_scroller.py       # 消息滚动显示
│  │  ├─ screen_manager.py         # 屏幕元素管理
│  │  ├─ life_mode.png             # 生活模式资源图
│  │  └─ sport_mode.png            # 运动模式资源图
│  ├─ tools/                       # 离线采集、分析、绘图工具
│  └─ utils/                       # 日志、调试、辅助函数
├─ server/                         # Flask 服务端与网页端资源
│  ├─ server.py                    # 服务端主入口
│  ├─ control.html                 # 控制台页面
│  ├─ history.html                 # 历史记录页面
│  ├─ sport_record_detail.html     # 运动详情页面
│  └─ data/                        # 服务端运行数据（JSON）
├─ data/                           # 顶层运行时数据目录
├─ debug_data/                     # 调试导出数据与图表
├─ logs/                           # 日志目录
├─ README.md                       # 项目主文档
├─ QUICKSTART.md                   # 快速启动指南
├─ PROJECT_STRUCTURE.md            # 本文档
├─ requirements.txt                # 服务端依赖
├─ start_server.bat                # Windows 启动脚本
└─ start_server.sh                 # Linux/macOS 启动脚本
```

## 关键模块说明

### `client/main.py`

- 设备端运行入口
- 负责模式切换、传感器读取、线程调度、状态汇总与上报
- 当前仓库中大部分运行时状态集中在这里

### `client/config.py`

- 设备端集中配置文件
- 包含服务端地址、硬件引脚、GNSS 参数、步数/姿态/跌倒阈值等

### `client/sensors/`

算法与底层传感器访问主要集中在这里：

- `icm20689.py`：惯性传感器读取
- `high_freq_sampler.py`：高频采样线程
- `gravity_remover.py`：重力分量去除
- `step_detector.py`：步数检测逻辑
- `posture_detector.py`：姿态识别逻辑
- `fall_detector.py`：跌倒检测逻辑
- `attitude.py`：姿态角与辅助计算

### `client/services/`

存放与“算法本体”相对独立的业务服务：

- `gnss_manager.py`：GNSS 驱动加载、定位点读取、速度/航向获取
- `offline_manager.py`：网络异常时缓存记录，恢复后自动补传

### `client/ui/`

负责屏幕与消息展示层逻辑：

- 模式界面切换
- 滚动消息显示
- 屏幕元素创建与隐藏

### `client/tools/`

主要用于开发与调试阶段的数据辅助：

- 数据采集
- 离线分析
- 曲线绘图
- 算法验证

这些脚本不属于设备端主运行链路，但对调参和复盘很重要。

### `client/utils/`

提供公共能力，例如：

- 日志管理
- 调试记录
- 配速、距离、减碳等辅助计算

### `server/server.py`

Flask 服务端主入口，负责：

- 接收设备端状态上报
- 保存历史记录、运动记录和设置项
- 提供 Web 页面和 JSON API
- 处理控制指令和离线同步请求

### `server/*.html`

网页端页面：

- `control.html`：主控制台
- `history.html`：历史记录页
- `sport_record_detail.html`：运动详情页

## 运行时数据目录

### `server/data/`

用于保存服务端 JSON 数据，例如：

- `settings.json`
- `history.json`
- `sport_records.json`
- `emergency.json`

### `data/`

顶层运行数据目录，通常用于本地联调或设备端输出的临时数据。

### `debug_data/`

用于保存调试阶段导出的：

- 原始采样 CSV
- 调试图表
- 离线分析结果

### `logs/`

保存程序运行日志。当前项目倾向于将同一次运行写入同一日志文件，便于排查问题。

## 建议阅读顺序

如果你第一次阅读这个项目，建议按下面顺序查看：

1. `README.md`
2. `QUICKSTART.md`
3. `client/main.py`
4. `client/sensors/`
5. `client/services/`
6. `server/server.py`

这样更容易从整体架构逐步进入具体实现。
