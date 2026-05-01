@echo off
chcp 65001 >nul
title OKX 交易助手 - 打包

echo ============================================
echo   OKX 交易助手 - Windows 打包脚本
echo ============================================
echo.

:: 激活虚拟环境
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

set PYTHONPATH=%~dp0

echo [1/3] 清理旧构建...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo [2/3] PyInstaller 打包...
pyinstaller ^
    --name "OKX交易助手" ^
    --onedir ^
    --noconfirm ^
    --clean ^
    --add-data "trading\templates;trading\templates" ^
    --add-data "trading\static;trading\static" ^
    --add-data "trading\config.py;trading" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    trading\run.py

if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo [3/3] 复制配置文件...
copy /y trading\requirements.txt dist\OKX交易助手\ >nul
copy /y README.md dist\OKX交易助手\ >nul
if not exist dist\OKX交易助手\trading\db mkdir dist\OKX交易助手\trading\db
if not exist dist\OKX交易助手\trading\logs mkdir dist\OKX交易助手\trading\logs

echo.
echo ============================================
echo   打包完成！
echo   输出目录: dist\OKX交易助手\
echo   启动文件: dist\OKX交易助手\OKX交易助手.exe
echo ============================================
pause
