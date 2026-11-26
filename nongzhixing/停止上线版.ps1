$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'hou\runtime\production.pid'
if (!(Test-Path -LiteralPath $pidFile)) {
    Write-Host '未找到 production.pid，服务可能未通过「启动上线版」启动。'
    exit 0
}
$saved = (Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8).Trim().Split('|')
$serverPid = [int]$saved[0]
$serverPort = [int]$saved[1]
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($process) {
    # venv 的 python.exe 会再启动一个子进程，用 /T 连同子进程一起结束，避免端口残留
    & taskkill /PID $serverPid /T /F | Out-Null
    Write-Host ("已停止农知行生产服务（PID {0}，端口 {1}）。" -f $serverPid, $serverPort)
} else {
    Write-Host '进程已经退出，清理残留的 pid 文件。'
}
Remove-Item -LiteralPath $pidFile -Force
