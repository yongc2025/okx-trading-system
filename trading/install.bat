@echo off
chcp 65001 >nul
title OKX 交易助手 - 安装

echo ============================================
echo   OKX 交易助手 - Windows 安装脚本
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] 创建虚拟环境...
python -m venv venv
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败
    pause
    exit /b 1
)

echo [2/4] 激活虚拟环境...
call venv\Scripts\activate.bat

echo [3/4] 安装依赖...
pip install -r trading\requirements.txt
pip install pyinstaller

echo [4/4] 安装完成！
echo.
echo 启动方式:
echo   方式一: 双击 start.bat
echo   方式二: python trading\run.py
echo.
pause
