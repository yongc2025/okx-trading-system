@echo off
chcp 65001 >nul
title OKX 交易助手

:: 激活虚拟环境
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: 设置 PYTHONPATH
set PYTHONPATH=%~dp0

:: 环境检查
echo 启动前检查...
python trading\check_env.py
if errorlevel 1 (
    echo.
    echo 环境检查未通过，请修复后重试
    pause
    exit /b 1
)
echo.

:: 启动
echo OKX 交易助手启动中...
echo 浏览器访问: http://localhost:8888
echo 按 Ctrl+C 停止
echo.
python trading\run.py

pause
