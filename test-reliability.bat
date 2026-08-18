@echo off
chcp 65001 >nul
REM ============================================================================
REM AI 视觉质检系统 - 可靠性测试工具
REM ============================================================================

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║     AI 视觉质检系统 - 可靠性测试工具                      ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [信息] Python 版本检查通过
echo.

REM 设置测试参数
set API_URL=http://localhost:8000/api/v1
set TEST_DURATION=30

:MENU
echo.
echo ════════════════════════════════════════════════════════════
echo 请选择测试模式:
echo ════════════════════════════════════════════════════════════
echo   1. 快速测试（约 1 分钟）
echo   2. 标准测试（约 3 分钟）
echo   3. 完整测试（约 5 分钟）
echo   4. 自定义测试
echo   5. 仅健康监控
echo   0. 退出
echo.

set /p choice="请输入选项 (0-5): "

if "%choice%"=="1" goto QUICK_TEST
if "%choice%"=="2" goto STANDARD_TEST
if "%choice%"=="3" goto FULL_TEST
if "%choice%"=="4" goto CUSTOM_TEST
if "%choice%"=="5" goto HEALTH_MONITOR
if "%choice%"=="0" goto EXIT

echo [错误] 无效的选项
goto MENU

:QUICK_TEST
echo.
echo ════════════════════════════════════════════════════════════
echo 开始快速测试...
echo ════════════════════════════════════════════════════════════
echo.
python tests\test_system_reliability.py --api-url %API_URL% --duration 15
goto END

:STANDARD_TEST
echo.
echo ════════════════════════════════════════════════════════════
echo 开始标准测试...
echo ════════════════════════════════════════════════════════════
echo.
python tests\test_system_reliability.py --api-url %API_URL% --duration 30
goto END

:FULL_TEST
echo.
echo ════════════════════════════════════════════════════════════
echo 开始完整测试...
echo ════════════════════════════════════════════════════════════
echo.
python tests\test_system_reliability.py --api-url %API_URL% --duration 60
goto END

:CUSTOM_TEST
echo.
echo ════════════════════════════════════════════════════════════
echo 自定义测试配置
echo ════════════════════════════════════════════════════════════
echo.
set /p custom_duration="请输入每个测试的时长（秒，默认 30）: "
if "%custom_duration%"=="" set custom_duration=30

echo.
python tests\test_system_reliability.py --api-url %API_URL% --duration %custom_duration%
goto END

:HEALTH_MONITOR
echo.
echo ════════════════════════════════════════════════════════════
echo 开始系统健康监控...
echo ════════════════════════════════════════════════════════════
echo.
set /p monitor_duration="请输入监控时长（秒，默认 60）: "
if "%monitor_duration%"=="" set monitor_duration=60

python tests\system_health_monitor.py --api-url %API_URL% --interval 5 --duration %monitor_duration%
goto END

:EXIT
echo.
echo [信息] 已退出测试工具
goto ENDALL

:END
echo.
echo ════════════════════════════════════════════════════════════
echo 测试完成！
echo ════════════════════════════════════════════════════════════
echo.

:ENDALL
pause
