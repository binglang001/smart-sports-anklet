# 快速开始指南

这是一个5分钟快速部署指南，帮助你快速运行运动腿环系统。

## 前提条件

- [ ] Python 3.7+ 已安装
- [ ] 行空板M10 硬件
- [ ] 传感器已连接（DHT11, LED, 按钮, 旋钮）
- [ ] 服务器和行空板在同一网络

## 步骤1：启动服务器 (2分钟)

### Windows

```bash
# 1. 打开命令提示符
# 2. 进入项目目录
cd path\to\smart-sports-anklet

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务器
python server.py
```

### Linux/Mac

```bash
# 1. 打开终端
# 2. 进入项目目录
cd path/to/smart-sports-anklet

# 3. 安装依赖
pip3 install -r requirements.txt

# 4. 启动服务器
python3 server.py
```

## 步骤2：配置客户端 (1分钟)

1. 查看你的服务器IP地址：
   - Windows: 打开cmd，输入 `ipconfig`，查看IPv4地址
   - Linux/Mac: 打开终端，输入 `ifconfig` 或 `hostname -I`

2. 编辑 `client.py` 文件第20行：
   ```python
   SERVER_URL = "http://YOUR_IP:5000"  # 替换YOUR_IP为服务器实际IP
   ```

## 步骤3：部署到行空板 (2分钟)

1. 连接行空板到电脑
2. 使用MindPlus或其他工具上传 `client.py`
3. 在行空板上运行程序

## 步骤4：验证系统 (1分钟)

1. 浏览器访问：`http://localhost:5000`
2. 应该看到控制界面
3. 检查设备状态是否显示"在线"
4. 行空板屏幕应显示系统界面

## 完成！🎉

现在你可以：
- ✅ 在Web界面查看实时数据
- ✅ 切换运动模式
- ✅ 接收健康提醒
- ✅ 查看历史数据

## 遇到问题？

### 设备显示离线
- 确认服务器正在运行
- 检查IP地址配置是否正确
- 确认防火墙未阻止5000端口

### 无法访问Web界面
```bash
# 尝试使用本机访问
http://127.0.0.1:5000

# 检查服务器是否启动
# 查看终端输出是否有错误
```

### 传感器数据异常
- 检查传感器接线
- 确认引脚配置正确
- 查看行空板串口日志

## 下一步

查看完整文档：[README.md](README.md)