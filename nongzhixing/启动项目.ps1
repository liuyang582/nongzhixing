$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'hou'
$frontendRoot = Join-Path $projectRoot 'qian'
$logRoot = Join-Path $backendRoot 'runtime'
function Test-LocalPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $client.Dispose() }
}
function Test-NxzBackend([int]$Port) {
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/health" -f $Port) -TimeoutSec 3
        return [bool]$health.database
    } catch { return $false }
}
# MySQL：优先复用已运行的实例，否则自动拉起 phpstudy 的 MySQL 8.0.12
$mysqlExe = 'D:\phpstudy_pro\Extensions\MySQL8.0.12\bin\mysqld.exe'
$mysqlIni = 'D:\phpstudy_pro\Extensions\MySQL8.0.12\my.ini'
if (!(Test-LocalPort 3306) -and (Test-Path -LiteralPath $mysqlExe) -and (Test-Path -LiteralPath $mysqlIni)) {
    Start-Process -FilePath $mysqlExe -ArgumentList @('--defaults-file='+$mysqlIni) -WorkingDirectory (Split-Path $mysqlExe) -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-LocalPort 3306) { break }
        Start-Sleep -Milliseconds 1000
    }
}
if (!(Test-LocalPort 3306)) { throw 'MySQL 尚未启动，请先启动本地 MySQL。' }
if (!(Test-LocalPort 6379)) {
    $redisLocationFile = Join-Path $logRoot 'redis-install.txt'
    if (Test-Path -LiteralPath $redisLocationFile) {
        $redisInstall = (Get-Content -LiteralPath $redisLocationFile -Raw -Encoding UTF8).Trim()
        $redisExe = Join-Path $redisInstall 'redis-server.exe'
        $redisConfig = Join-Path $redisInstall 'redis.conf'
        if ((Test-Path -LiteralPath $redisExe) -and (Test-Path -LiteralPath $redisConfig)) {
            $redisStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            Start-Process -FilePath $redisExe -ArgumentList @('redis.conf') -WorkingDirectory $redisInstall -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot ('redis-'+$redisStamp+'.out.log')) -RedirectStandardError (Join-Path $logRoot ('redis-'+$redisStamp+'.err.log')) | Out-Null
        }
    }
}
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonExe)) { throw '缺少后端虚拟环境，请查看 README 的安装说明。' }
$nodeExe = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (!$nodeExe -and (Test-Path -LiteralPath 'C:\nvm4w\nodejs\node.exe')) { $nodeExe = 'C:\nvm4w\nodejs\node.exe' }
if (!$nodeExe) { throw '未找到 Node.js，请安装 Node.js 后重新运行。' }
$viteEntry = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
if (!(Test-Path -LiteralPath $viteEntry)) { throw '缺少前端依赖，请在 qian 目录执行 npm install。' }
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

# 选择一个可用（或已被本项目占用）的后端端口，避免与其他项目冲突
$backendPort = 0
foreach ($candidate in 8000, 8001, 8002, 8003, 8004, 8010) {
    if (!(Test-LocalPort $candidate)) { $backendPort = $candidate; break }
    if (Test-NxzBackend $candidate) { $backendPort = $candidate; break }
}
if ($backendPort -eq 0) { throw '8000-8010 均被其他应用占用，请先释放端口。' }
if (!(Test-NxzBackend $backendPort)) {
    Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$backendPort") -WorkingDirectory $backendRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot ('backend-'+"$backendPort"+'.out.log')) -RedirectStandardError (Join-Path $logRoot ('backend-'+"$backendPort"+'.err.log')) | Out-Null
}
# 后端首次冷启动需要加载数据库与 AI 依赖，最多等 60 秒
$backendReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Test-NxzBackend $backendPort) { $backendReady = $true; break }
    Start-Sleep -Milliseconds 1000
}
if (!$backendReady) { throw ("后端 {0} 端口 60 秒内未就绪，请查看 hou\runtime\backend-{0}.err.log" -f $backendPort) }

# 前端：优先复用已运行的本项目页面，否则依次尝试 5173-5176
$frontendPort = 0
foreach ($candidate in 5173, 5174, 5175, 5176) {
    if (Test-LocalPort $candidate) {
        # 通过首页标题判断是否为本项目页面：只看 /api/health 会被其他项目（同样代理到本后端）误判
        try {
            $page = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/" -f $candidate) -UseBasicParsing -TimeoutSec 2
            if ($page.StatusCode -eq 200 -and ($page.Content -match '农知行' -or $page.Content -match '/src/main\.ts')) { $frontendPort = $candidate; break }
        } catch { }
        continue
    }
    $env:VITE_API_TARGET = "http://127.0.0.1:$backendPort"
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Start-Process -FilePath $nodeExe -ArgumentList @(('"'+$viteEntry+'"'),'--host','127.0.0.1','--port',"$candidate",'--strictPort') -WorkingDirectory $frontendRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot ('frontend-'+$stamp+'-'+$candidate+'.out.log')) -RedirectStandardError (Join-Path $logRoot ('frontend-'+$stamp+'-'+$candidate+'.err.log')) | Out-Null
    $frontendReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-LocalPort $candidate) { $frontendReady = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if ($frontendReady) { $frontendPort = $candidate; break }
}
if ($frontendPort -eq 0) { throw '5173-5176 均无法使用，请查看 hou\runtime 中的前端日志。' }

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/health" -f $backendPort) -TimeoutSec 2
        $page = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}" -f $frontendPort) -UseBasicParsing -TimeoutSec 2
        if ($health.database -and $page.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 800 }
}
if (!$ready) { throw '启动后未收到前后端正常响应，请查看 hou\runtime 中的日志。' }
if (!(Test-LocalPort 6379)) { Write-Warning 'Redis 尚未启动，请检查安装位置和 runtime 中的 Redis 日志。' }
Write-Host ("农知行前后端已就绪。请在浏览器打开：http://127.0.0.1:{0}" -f $frontendPort)
Write-Host ("后端接口：http://127.0.0.1:{0}/api/health" -f $backendPort)
Write-Host '若页面无法打开，请查看 hou\runtime 中的日志。'
