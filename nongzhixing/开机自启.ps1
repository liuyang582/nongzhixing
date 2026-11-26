param(
    # 加 -Remove 取消开机自启
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$taskName = '农知行智慧农业平台'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host '已取消农知行开机自启。'
    exit 0
}
$script = Join-Path $PSScriptRoot '启动上线版.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script)
# 登录当前账号后自动启动；MySQL（phpstudy）也依赖用户会话，比开机服务更稳妥
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description '登录后自动启动农知行本地生产服务（前端与 FastAPI 同源，端口 8080）' -Force | Out-Null
Write-Host '已设置开机自启：登录 Windows 后将自动运行「启动上线版.ps1」。'
Write-Host '取消方法：在任务计划程序中删除「农知行智慧农业平台」任务，或执行：'
Write-Host 'powershell -ExecutionPolicy Bypass -File .\开机自启.ps1 -Remove'
