@echo off
chcp 65001 >nul
echo 正在配置局域网访问（需要管理员权限）...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0放行局域网端口.ps1"
pause
