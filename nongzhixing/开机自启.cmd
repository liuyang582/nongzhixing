@echo off
chcp 65001 >nul
echo 正在设置农知行开机自启...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0开机自启.ps1"
echo.
echo 取消自启请执行：powershell -ExecutionPolicy Bypass -File "%~dp0开机自启.ps1" -Remove
pause
