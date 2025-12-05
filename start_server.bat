@echo off
chcp 65001 >nul
echo ========================================
echo     运动腿环系统 - 服务器启动脚本
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到Python，请先安装Python 3.7+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 检查Python环境... ✓
echo.

REM 检查依赖是否安装
echo [2/3] 检查依赖包...
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 依赖包未安装，正在安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo [完成] 依赖安装成功 ✓
) else (
    echo [完成] 依赖已安装 ✓
)
echo.

REM 创建数据目录
if not exist "data" mkdir data
echo [3/3] 数据目录准备完成 ✓
echo.

echo ========================================
echo     正在启动服务器...
echo ========================================
echo.
echo [提示] 按 Ctrl+C 停止服务器
echo [提示] 访问地址: http://localhost:5000
echo.

REM 启动服务器
python server.py

pause