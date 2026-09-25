@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ============================================================
rem  AI 情报站 · 一键启动（API + 静态站）
rem    API 是 AI 问答 / 人工审核的依赖；资讯流与关系图谱只读静态文件，
rem    即使 API 没起来也能照常浏览 —— 所以两个服务分开起、互不阻塞。
rem ============================================================

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "HEALTH=http://127.0.0.1:8000/health"

echo ============================================================
echo  AI 情报站 · 一键启动
echo  ------------------------------------------------------------
echo  API 服务   http://127.0.0.1:8000/docs   接口文档（AI 问答、人工审核需要）
echo  静态站点  http://127.0.0.1:8765/       资讯流与关系图谱（不依赖 API）
echo  两个窗口各自打印日志，关掉对应窗口即停止该服务
echo ============================================================
echo.

if not exist ".env" echo [提示] 没有 .env，AI 问答会提示未配置 DEEPSEEK_API_KEY；其余功能不受影响。
echo.

rem ---------- 1/3 启动 API（已在运行则复用，避免端口冲突） ----------
set "PROBE_OK="
where curl >nul 2>&1
if not errorlevel 1 (
    curl -s -f --noproxy "*" -m 2 -o nul "%HEALTH%" >nul 2>&1
    if not errorlevel 1 set "PROBE_OK=1"
)

if defined PROBE_OK (
    echo [1/3] 8000 端口已有健康 API 在运行，直接复用
) else (
    echo [1/3] 启动 API 服务（端口 8000）...
    start "AI 情报站 API" cmd /k ""%PY%" -m uvicorn api.main:app --host 127.0.0.1 --port 8000"
)

rem ---------- 2/3 等 API 就绪（首次启动要加载依赖，冷启动约 10 秒） ----------
echo [2/3] 等待 API 就绪...
timeout /t 10 /nobreak >nul

set "PROBE_OK="
where curl >nul 2>&1
if errorlevel 1 (
    echo       [提示] 系统没有 curl，跳过自动探活；问答报错时请看 API 窗口日志
) else (
    curl -s -f --noproxy "*" -m 3 -o nul "%HEALTH%" >nul 2>&1
    if not errorlevel 1 set "PROBE_OK=1"
)

if defined PROBE_OK (
    echo       API 已就绪
) else (
    where curl >nul 2>&1
    if not errorlevel 1 (
        echo       [提示] 探活未通过。API 窗口没有报错的话再等几秒刷新页面即可；
        echo              若是有个卡住的旧 API 窗口占着 8000 端口，先关掉它再重跑本脚本。
    )
)

rem ---------- 3/3 启动静态站并打开浏览器 ----------
set "WEB_OK="
where curl >nul 2>&1
if not errorlevel 1 (
    curl -s -f --noproxy "*" -m 2 -o nul "http://127.0.0.1:8765/" >nul 2>&1
    if not errorlevel 1 set "WEB_OK=1"
)

if defined WEB_OK (
    echo [3/3] 8765 端口已有静态站在运行，直接复用
) else (
    echo [3/3] 启动静态站点（端口 8765）...
    start "AI 情报站 前端" /d "%~dp0web" cmd /k ""%PY%" -m http.server 8765 --bind 127.0.0.1"
    timeout /t 2 /nobreak >nul
)

start "" http://127.0.0.1:8765/

echo.
echo 已就绪：浏览器会自动打开 http://127.0.0.1:8765/
echo 关闭「AI 情报站 API」「AI 情报站 前端」两个窗口即可停止服务，本窗口可直接关掉。
endlocal
