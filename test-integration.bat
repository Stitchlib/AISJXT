@echo off
chcp 65001 >nul
title AI视觉质检系统 - 前后端集成测试

echo ============================================================
echo AI视觉质检系统 - 前后端集成验证工具
echo ============================================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [信息] Python 版本检查通过
python --version
echo.

REM 检查 Node.js 是否安装
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 未检测到 Node.js，前端功能可能无法使用
    echo [提示] 如需测试前端，请安装 Node.js 16+
    echo.
) else (
    echo [信息] Node.js 版本检查通过
    node --version
    echo npm --version
    echo.
)

echo ============================================================
echo 请选择测试模式:
echo.
echo 1. 仅测试后端 API（推荐首次使用）
echo 2. 测试前后端完整集成（需要先启动后端和前端）
echo 3. 运行完整测试套件（包含 WebSocket 测试）
echo 4. 退出
echo.
set /p choice=请输入选项 (1-4): 

if "%choice%"=="1" goto test_backend_only
if "%choice%"=="2" goto test_full_integration
if "%choice%"=="3" goto run_full_tests
if "%choice%"=="4" goto end

echo [错误] 无效的选项
pause
exit /b 1

:test_backend_only
echo.
echo ============================================================
echo 开始测试后端 API...
echo ============================================================
echo.

REM 检查后端服务是否运行
curl -s http://localhost:8000/api/v1/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 后端服务未运行，请先启动 edge/main.py
    echo [提示] 运行命令：cd edge ^&^& python main.py
    pause
    exit /b 1
)

echo [成功] 后端服务正在运行
echo.

REM 运行基础 API 测试
python tests\integration\test_frontend_backend_integration.py
if %errorlevel% equ 0 (
    echo.
    echo [成功] 后端 API 测试全部通过！
) else (
    echo.
    echo [失败] 部分测试未通过，请检查日志
)
goto menu_return

:test_full_integration
echo.
echo ============================================================
echo 开始测试前后端集成...
echo ============================================================
echo.

REM 检查后端服务
curl -s http://localhost:8000/api/v1/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 后端服务未运行
    echo [提示] 请先启动 edge/main.py
    pause
    exit /b 1
)

echo [成功] 后端服务正在运行
echo.

REM 检查前端服务
curl -s http://localhost:5173 >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] 前端服务未运行在 http://localhost:5173
    echo [提示] 请先启动前端：cd frontend ^&^& npm run dev
    echo.
    set /p continue=是否继续测试后端？(Y/N): 
    if /i "%continue%"=="Y" goto test_backend_only
    pause
    exit /b 1
)

echo [成功] 前端服务正在运行
echo.

REM 运行集成测试
python tests\integration\test_frontend_backend_integration.py
if %errorlevel% equ 0 (
    echo.
    echo [成功] 前后端集成测试通过！
    echo.
    echo 下一步操作:
    echo 1. 打开浏览器访问：http://localhost:5173
    echo 2. 导航到"实时质检"页面
    echo 3. 选择摄像头并点击"开始检测"
    echo 4. 观察实时数据更新
) else (
    echo.
    echo [失败] 部分测试未通过
)
goto menu_return

:run_full_tests
echo.
echo ============================================================
echo 运行完整测试套件（包含 WebSocket 测试）
echo ============================================================
echo.

REM 安装测试依赖（如果需要）
pip show websocket-client >nul 2>&1
if %errorlevel% neq 0 (
    echo [信息] 正在安装 websocket-client 用于 WebSocket 测试...
    pip install websocket-client requests
)

REM 检查后端服务
curl -s http://localhost:8000/api/v1/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 后端服务未运行
    pause
    exit /b 1
)

echo [信息] 开始运行完整测试...
echo.

python tests\integration\test_frontend_backend_integration.py

if %errorlevel% equ 0 (
    echo.
    echo [成功] 所有测试通过！
) else (
    echo.
    echo [失败] 部分测试未通过
)
goto menu_return

:menu_return
echo.
echo ============================================================
echo 测试完成！
echo ============================================================
echo.
echo 接下来可以:
echo 1. 查看测试日志了解详细信息
echo 2. 访问 http://localhost:8000/api/v1/docs 查看 API 文档
echo 3. 访问 http://localhost:5173 使用前端界面
echo.
pause
exit /b 0

:end
echo.
echo 感谢使用，再见！
pause
exit /b 0
