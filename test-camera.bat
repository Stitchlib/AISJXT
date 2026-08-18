@echo off
chcp 65001 >nul
echo ================================================
echo   摄像头管理功能 - 快速测试启动器
echo ================================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python
    pause
    exit /b 1
)

echo [信息] Python 版本检查通过
python --version
echo.

REM 询问用户选择测试模式
echo 请选择测试模式:
echo 1. 快速验证（适合开发过程快速测试）
echo 2. 完整测试（包含详细验证和交互）
echo 3. 仅启动后端服务
echo.
set /p mode="请输入选择 (1/2/3): "

if "%mode%"=="3" (
    echo.
    echo [信息] 启动后端服务...
    cd edge
    python main.py
    exit /b 0
)

if "%mode%"=="2" (
    echo.
    echo [信息] 运行完整测试...
    python test-camera-management.py
    if %errorlevel% neq 0 (
        echo.
        echo [提示] 测试失败，是否需要启动后端服务？
        set /p start_backend="启动后端服务？(y/n): "
        if /i "%start_backend%"=="y" (
            cd edge
            python main.py
        )
    )
    exit /b 0
)

if "%mode%"=="1" (
    echo.
    echo [信息] 运行快速验证...
    python quick-test-camera.py
    if %errorlevel% neq 0 (
        echo.
        echo [提示] 测试失败，可能需要启动后端服务
        echo.
        set /p start_backend="是否启动后端服务？(y/n): "
        if /i "%start_backend%"=="y" (
            cd edge
            python main.py
        )
    ) else (
        echo.
        echo ================================================
        echo   测试完成！
        echo ================================================
        echo.
        echo 下一步操作:
        echo 1. 查看测试输出结果
        echo 2. 访问前端界面测试 UI 功能
        echo 3. 查看详细文档：docs\摄像头管理功能测试指南.md
        echo.
    )
    exit /b 0
)

echo [错误] 无效的选择
pause
