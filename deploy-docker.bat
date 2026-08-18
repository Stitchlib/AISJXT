@echo off
chcp 65001 >nul
echo ============================================================
echo AI 视觉质检系统 - Docker 快速部署工具
echo ============================================================
echo.

cd /d "%~dp0"

:menu
echo.
echo 请选择操作：
echo.
echo [1] 首次部署（构建并启动）
echo [2] 启动所有服务
echo [3] 停止所有服务
echo [4] 重启所有服务
echo [5] 查看服务状态
echo [6] 查看实时日志
echo [7] 重新构建镜像
echo [8] 清理无用资源
echo [9] 备份数据
echo [0] 退出
echo.
set /p choice=请输入选项 (0-9): 

if "%choice%"=="1" goto deploy_first
if "%choice%"=="2" goto start_all
if "%choice%"=="3" goto stop_all
if "%choice%"=="4" goto restart_all
if "%choice%"=="5" goto show_status
if "%choice%"=="6" goto show_logs
if "%choice%"=="7" goto rebuild
if "%choice%"=="8" goto cleanup
if "%choice%"=="9" goto backup_data
if "%choice%"=="0" goto exit_program

echo 无效的选项，请重新输入！
goto menu

:deploy_first
echo.
echo ============================================================
echo 正在执行首次部署...
echo ============================================================
echo.
echo [1/3] 构建 Docker 镜像...
docker-compose build

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 构建失败！请检查错误信息。
    pause
    goto menu
)

echo.
echo [2/3] 启动服务...
docker-compose up -d

echo.
echo [3/3] 验证服务状态...
timeout /t 10 /nobreak >nul
docker-compose ps

echo.
echo ============================================================
echo ✅ 部署完成！
echo ============================================================
echo.
echo 访问地址：
echo   前端：http://localhost
echo   后端 API: http://localhost:8000/api/v1
echo   API 文档：http://localhost:8000/api/v1/docs
echo.
echo 默认账户：admin / admin123 （首次登录后必须修改！）
echo.
pause
goto menu

:start_all
echo.
echo 正在启动所有服务...
docker-compose up -d
echo.
echo ✅ 启动完成！
pause
goto menu

:stop_all
echo.
echo 正在停止所有服务...
docker-compose down
echo.
echo ✅ 停止完成！
pause
goto menu

:restart_all
echo.
echo 正在重启所有服务...
docker-compose restart
echo.
echo ✅ 重启完成！
pause
goto menu

:show_status
echo.
echo 服务状态：
echo.
docker-compose ps
echo.
pause
goto menu

:show_logs
echo.
echo 正在查看实时日志...（按 Ctrl+C 退出）
echo.
docker-compose logs -f
goto menu

:rebuild
echo.
echo ============================================================
echo 正在重新构建镜像...
echo ============================================================
echo.
echo [1/2] 停止当前服务...
docker-compose down

echo.
echo [2/2] 不使用缓存重新构建...
docker-compose build --no-cache

echo.
echo 构建完成！是否启动服务？
set /p start_now=是否启动服务？(Y/N): 
if /i "%start_now%"=="Y" (
    docker-compose up -d
    echo.
    echo ✅ 服务已启动！
)

pause
goto menu

:cleanup
echo.
echo ⚠️ 警告：此操作将删除所有未使用的 Docker 资源
echo.
set /p confirm=确认继续？(Y/N): 
if /i not "%confirm%"=="Y" goto menu

echo.
echo 正在清理...
docker system prune -f
docker volume prune -f
echo.
echo ✅ 清理完成！
pause
goto menu

:backup_data
echo.
echo 正在备份数据...
echo.

set BACKUP_DIR=backup_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set BACKUP_DIR=%BACKUP_DIR: =%

if not exist "backups" mkdir backups

echo 备份目录：backups\%BACKUP_DIR%
mkdir "backups\%BACKUP_DIR%"

echo 复制数据文件...
xcopy /E /I /Y edge\data "backups\%BACKUP_DIR%\data"
xcopy /E /I /Y edge\logs "backups\%BACKUP_DIR%\logs"
xcopy /E /I /Y edge\models "backups\%BACKUP_DIR%\models"
xcopy /E /I /Y edge\config "backups\%BACKUP_DIR%\config"

echo.
echo ✅ 数据备份完成！
echo 备份位置：backups\%BACKUP_DIR%
echo.
pause
goto menu

:exit_program
echo.
echo 感谢使用，再见！
echo.
exit /b 0
