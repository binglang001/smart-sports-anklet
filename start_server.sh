#!/bin/bash

# 运动腿环系统 - 服务器启动脚本

echo "========================================"
echo "    运动腿环系统 - 服务器启动脚本"
echo "========================================"
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python3，请先安装Python 3.7+"
    exit 1
fi

echo "[1/3] 检查Python环境... ✓"
echo ""

# 检查依赖是否安装
echo "[2/3] 检查依赖包..."
if ! python3 -c "import flask" &> /dev/null; then
    echo "[提示] 依赖包未安装，正在安装..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[错误] 依赖安装失败"
        exit 1
    fi
    echo "[完成] 依赖安装成功 ✓"
else
    echo "[完成] 依赖已安装 ✓"
fi
echo ""

# 创建数据目录
if [ ! -d "data" ]; then
    mkdir data
fi
echo "[3/3] 数据目录准备完成 ✓"
echo ""

echo "========================================"
echo "    正在启动服务器..."
echo "========================================"
echo ""
echo "[提示] 按 Ctrl+C 停止服务器"
echo "[提示] 访问地址: http://localhost:5000"
echo ""

# 启动服务器
python3 server.py