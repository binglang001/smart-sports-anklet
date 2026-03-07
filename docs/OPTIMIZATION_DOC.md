# 智能运动腰带系统 - 完整技术文档

## 一、项目背景

### 1.1 项目概述

这是一个运行在行空板M10上的智能运动腰带系统，主要功能包括：
- 步数检测
- 姿态识别（坐姿/站立/行走）
- 跌倒检测
- 与Flask服务器通信
- Web控制界面

### 1.2 核心文件

| 文件 | 功能 |
|------|------|
| `client.py` | 行空板客户端主程序（约2000行） |
| `server.py` | Flask服务器，提供REST API |
| `config.py` | 配置文件，包含算法参数 |
| `control.html` | Web控制界面 |
| `加速度传感器算法总结.md` | 算法论文分析文档（约70KB） |

---

## 二、问题诊断过程

### 2.1 用户反馈的问题

用户在实际测试中遇到以下问题：

1. **坐姿检测失败**
   - 将行空板放置于后腰正中心（腰椎处）
   - 站立姿态正常检测
   - 坐下并调整坐姿，未被检测到

2. **步数检测严重漏报**
   - 走了数十步却只触发几次
   - 触发时机与实际步伐相差很远

3. **小幅度动作误判**
   - 小幅度动作被判断为运动
   - 移动行空板位置被误判为步数增加

4. **跌倒检测**：暂未测试

### 2.2 调试数据分析

从 `debug_data/debug_20260301_001044.csv` 分析得到：

```
【站立阶段】(roll > 80°)
  样本数: 52
  roll范围: 80.1 - 87.6°
  加速度幅值: ~0.95g

【坐下状态】
  roll范围: 64.5 - 87.8° (平均75.1°)
  加速度幅值: 0.7868 - 1.4151g

【行走阶段】
  样本数: 56
  检测到步数: 6次（实际走了数十步！）
  标准差范围: 0.0044 - 0.1883 (平均0.0815)

【关键发现】
  站立roll均值: 84.3°
  坐下roll均值: 75.1°
  roll变化: 仅9.2°（不足以区分坐站！）
  pitch变化: 仅0.3°（几乎不变！）
```

### 2.3 采样频率问题

通过分析调试数据的时间戳：

```
Posture记录数: 180
平均采样间隔: 166.3 ms
推算采样频率: 6.01 Hz

Step记录数: 56
平均采样间隔: 1163.2 ms
推算采样频率: 0.86 Hz  ← 严重不足！
```

### 2.4 算法问题分析

#### 步数检测bug

查看 `client.py` 第205-232行，发现当前代码：

```python
# 当前实现（错误！）
def _detect_peak(self, acc_values, mean_acc, std_acc):
    # 使用较低的阈值
    sensitivity = self.config.get("sensitivity", 1.0)
    # 注释说"因为腰部行走时加速度会降低，所以我们检测"波谷"而不是"波峰""
    dynamic_threshold = mean_acc - std_acc * sensitivity  # ← 这是检测"低于均值"！

    if current_acc > dynamic_threshold:  # ← 逻辑反了！
        return False
```

**问题**：代码在检测"波谷"而不是"波峰"！

```
实测峰值数量: 18个
符合"波谷<均值-标准差"的数量: 7个
实际检测到的步数: 6步
结论: 应该检测波峰而非波谷！
```

---

## 三、解决方案探索过程

### 3.1 最初方案：算法优化

根据论文《加速度传感器算法总结.md》（约70KB的详细分析），提出：

| 功能 | 推荐的算法 |
|------|------------|
| 步数 | 多阈值峰值检测 + 自适应阈值 |
| 坐姿 | Y轴重力分量法 + 动态基线 |
| 跌倒 | 三阶段阈值法 |

### 3.2 采样频率问题

但发现**核心问题是采样频率不足**，无论什么算法都无法准确。

分析行空板M10架构：
```
RK3308 (1.2GHz 4核) ← 运行Python
    ↓ I2C通信（每次5-20ms延迟）
GD32VF103 (108MHz) ← 控制传感器
    ↓
ICM20689 ← 加速度传感器
```

### 3.3 关键发现：/dev/icm20689

用户在行空板上运行 `ls -la /dev`，发现：

```
crw------- 1 root root 244, 0 icm20689  ← 专用设备！
crw-rw-r-- 1 root i2c  89, 1 i2c-1    ← 标准I2C
```

### 3.4 测试过程

#### 第一次测试（test_i2c_direct.py）

- 发现设备存在但读取失败
- 发现权限问题（600）

#### 用户自行探索

用户写了更完整的测试脚本，发现：

```bash
# 读取成功！
hexdump -C /dev/icm20689
# 输出：02003b001d08 (6字节)

# 解析结果
X=2, Y=59, Z=2077  # 原始int16值

# 高频测试
总样本数: 99
测试时长: 2.00秒
实际频率: 49.49Hz  ← 完美50Hz！

✓ 成功达到或接近50Hz采样！
```

---

## 四、ICM20689直接读取实现

### 4.1 设备信息

```
设备路径: /dev/icm20689
权限: 600 (root专属)
类型: 字符设备 (244, 0)
```

### 4.2 数据格式

```
长度: 6字节
字节序: 小端 (little-endian)
内容: X(2字节), Y(2字节), Z(2字节)
类型: int16 (有符号16位整数)

解析代码:
  import struct
  x, y, z = struct.unpack('<hhh', data)
```

### 4.3 转换为g值

```
灵敏度: 16384 LSB/g (ICM20689默认±2g范围)

x_g = x / 16384.0
y_g = y / 16384.0
z_g = z / 16384.0
```

### 4.4 采样频率

```
目标: 50Hz
实测: 49.49Hz ✅
```

### 4.5 完整代码示例

```python
import os
import struct
import time

# 初始化
ICM_FD = os.open('/dev/icm20689', os.O_RDONLY)

# 读取加速度
def read_accel():
    data = os.read(ICM_FD, 6)
    x, y, z = struct.unpack('<hhh', data)
    return x / 16384.0, y / 16384.0, z / 16384.0

# 50Hz采样循环
for _ in range(100):
    x, y, z = read_accel()
    print(f"X={x:.4f}g Y={y:.4f}g Z={z:.4f}g")
    time.sleep(0.02)  # 50Hz = 20ms间隔
```

---

## 五、算法改进方案

### 5.1 步数检测（需修复）

#### 当前问题
- 检测波谷而非波峰
- 阈值不适合低频采样

#### 修复方案
```python
def _detect_peak(self, acc_values, mean_acc, std_acc):
    """正确的波峰检测"""
    if len(acc_values) < 3:
        return False

    # 找到窗口中间位置
    mid_idx = len(acc_values) // 2
    current_acc = acc_values[mid_idx]
    prev_acc = acc_values[mid_idx - 1]
    next_acc = acc_values[mid_idx + 1]

    # 波峰条件：当前点比前后都大
    is_peak = (current_acc > prev_acc and current_acc > next_acc)

    if not is_peak:
        return False

    # 波峰阈值：峰值 > 均值 + 0.8×标准差
    peak_threshold = mean_acc + std_acc * 0.8

    if current_acc < peak_threshold:
        return False

    return True
```

### 5.2 坐姿检测（需重新设计）

#### 当前问题
- Roll变化仅9°，不足以区分
- Pitch几乎不变

#### 新方案：Y轴分量法
```python
# 站立时：Y轴重力分量为0
# 坐下时：Y轴重力分量变化明显

def _determine_posture_by_y(self, acc_y, baseline_y):
    delta_y = abs(acc_y - baseline_y)

    if delta_y > 0.15:  # 坐下阈值
        return "sitting"
    elif delta_y < 0.10:  # 站立阈值
        return "standing"
    else:
        return self.current_posture  # 保持状态
```

### 5.3 配置参数建议

```python
# config.py

STEP_CONFIG = {
    "window_size": 8,
    "min_interval_ms": 300,
    "max_interval_ms": 1500,
    "use_peak_detection": True,
    "peak_threshold_ratio": 1.08,
}

POSTURE_CONFIG = {
    "y_baseline_samples": 30,
    "y_sit_threshold": 0.15,
    "y_stand_threshold": 0.10,
    "stillness_duration": 2.0,
    "hysteresis_count": 5,
}

FALL_CONFIG = {
    "freefall_threshold": 0.5,
    "impact_threshold": 1.8,
    "static_duration_min": 1.5,
    "static_duration_max": 5.0,
}
```

---

## 六、需要完成的任务

### 6.1 高优先级

| # | 任务 | 状态 | 说明 |
|---|------|------|------|
| 1 | ✅ 发现/dev/icm20689设备 | 已完成 | 50Hz采样 |
| 2 | ✅ 确定数据解析格式 | 已完成 | 6字节小端序int16 |
| 3 | ⏳ 整合新加速度读取到client.py | 待完成 | 替换pinpong库 |
| 4 | ⏳ 修复步数检测bug | 待完成 | 波谷→波峰 |
| 5 | ⏳ 添加坐姿Y轴检测 | 待完成 | 新算法 |
| 6 | ⏳ 测试验证 | 待完成 | 准确率提升 |

### 6.2 中优先级

| # | 任务 | 说明 |
|---|------|------|
| 7 | 优化步数检测参数 | 根据实测调整阈值 |
| 8 | 测试跌倒检测 | 暂未测试 |
| 9 | 优化主循环结构 | 分离采样与处理 |

### 6.3 低优先级

| # | 任务 | 说明 |
|---|------|------|
| 10 | 添加调试数据记录 | 验证新算法效果 |
| 11 | 性能优化 | 减少CPU占用 |

---

## 七、已创建的文件

| 文件 | 说明 |
|------|------|
| `test_i2c_direct.py` | 初步I2C测试脚本 |
| `test_i2c_ioctl.py` | ioctl方式测试脚本 |
| `TEST_README.md` | 测试说明文档 |
| `OPTIMIZATION_DOC.md` | 优化文档（本文档前身） |

---

## 八、技术要点速查

### 8.1 关键数据

```
/dev/icm20689 采样频率: 50Hz (实测49.49Hz)
数据格式: 6字节, 小端序, 3×int16
灵敏度: 16384 LSB/g
```

### 8.2 核心代码

```python
import os, struct

# 读取加速度
fd = os.open('/dev/icm20689', os.O_RDONLY)
data = os.read(fd, 6)
x, y, z = struct.unpack('<hhh', data)
x_g, y_g, z_g = x/16384, y/16384, z/16384
```

### 8.3 注意事项

1. 需要root权限运行
2. 设备只能打开一次
3. 解析必须是`<hhh`格式
4. 建议50Hz采样间隔20ms

---

## 九、下一步工作流程

新对话应该按以下顺序执行：

1. **阅读本文档** - 了解全部背景和问题
2. **阅读 `client.py`** - 找到需要修改的位置
3. **阅读 `config.py`** - 了解当前参数
4. **实现任务1** - 整合新的加速度读取
5. **实现任务2** - 修复步数检测bug
6. **实现任务3** - 添加坐姿Y轴检测
7. **测试验证** - 运行程序验证效果

---

## 附录：提供给新对话的Prompt

```
请阅读以下内容，了解项目现状和需要完成的任务：

1. 项目是一个运行在行空板M10上的智能运动腰带系统
2. 核心问题：采样频率不足（实测0.86Hz）和算法bug
3. 关键发现：/dev/icm20689可以直接50Hz采样，格式为6字节小端序int16
4. 需要完成的任务：
   - 将新的加速度读取方式整合到client.py
   - 修复步数检测的波峰/波谷bug
   - 添加基于Y轴的坐姿检测
5. 请先阅读OPTIMIZATION_DOC.md和client.py，了解详细背景后开始工作
```

---

最后更新: 2026-03-01
