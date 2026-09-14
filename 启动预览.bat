@echo off
chcp 65001 >nul
cd /d "%~dp0web"
echo AI 情报站本地预览启动中...
echo 浏览器打开: http://127.0.0.1:8765/
echo 关闭本窗口即停止服务
start "" http://127.0.0.1:8765/
python -m http.server 8765 --bind 127.0.0.1
pause
