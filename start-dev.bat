@echo off
REM ============================================================
REM  AI 视觉质检系统 - 开发启动脚本（真实可用版）
REM  修复原 launch.bat / quick-start.bat 调用 mvn 与缺失入口的问题
REM  前置：已执行  .venv/Scripts/python.exe -m pip install ...（后端依赖）
REM        前端已在 frontend/ 完成 npm install
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 .venv，请先创建虚拟环境并安装后端依赖。
    pause
    exit /b 1
)

echo 正在启动后端 (FastAPI :8000) ...
REM 必须从 edge/ 目录内部启动，使内部 `from src.xxx import ...` 正常解析，并避免
REM `uvicorn edge.main:app` 从仓库根启动时出现的 WebSocket /ws 路由 404 问题。
start "AI质检-后端" cmd /k "cd /d %~dp0edge && ..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000"

echo 正在启动前端 (Vite :3000) ...
start "AI质检-前端" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo 后端 API 文档:  http://localhost:8000/docs
echo 前端界面:       http://localhost:3000
echo.
pause
