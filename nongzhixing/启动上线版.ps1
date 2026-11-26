param(
    # 强制重新构建前端
    [switch]$Rebuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'hou'
$frontendRoot = Join-Path $projectRoot 'qian'
$logRoot = Join-Path $backendRoot 'runtime'
$pidFile = Join-Path $logRoot 'production.pid'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

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
# 通过默认路由找到当前联网网卡的 IPv4 地址（跳过 WSL / 虚拟网卡）
function Get-LanAddress {
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
        return (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction Stop |
            Select-Object -First 1).IPAddress
    } catch { return $null }
}

# 1. 检查并启动 MySQL（优先复用已运行实例，否则拉起 phpstudy 的 MySQL）
$mysqlExe = 'D:\phpstudy_pro\Extensions\MySQL8.0.12\bin\mysqld.exe'
$mysqlIni = 'D:\phpstudy_pro\Extensions\MySQL8.0.12\my.ini'
if (!(Test-LocalPort 3306) -and (Test-Path -LiteralPath $mysqlExe) -and (Test-Path -LiteralPath $mysqlIni)) {
    Start-Process -FilePath $mysqlExe -ArgumentList @('--defaults-file='+$mysqlIni) -WorkingDirectory (Split-Path $mysqlExe) -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-LocalPort 3306) { break }
        Start-Sleep -Milliseconds 1000
    }
}
if (!(Test-LocalPort 3306)) { throw 'MySQL 尚未启动，请先启动本地 MySQL（phpstudy 面板或服务）。' }

# 2. 检查并启动 Redis（安装位置记录在 hou/runtime/redis-install.txt）
if (!(Test-LocalPort 6379)) {
    $redisLocationFile = Join-Path $logRoot 'redis-install.txt'
    if (Test-Path -LiteralPath $redisLocationFile) {
        $redisInstall = (Get-Content -LiteralPath $redisLocationFile -Raw -Encoding UTF8).Trim()
        $redisExe = Join-Path $redisInstall 'redis-server.exe'
        $redisConfig = Join-Path $redisInstall 'redis.conf'
        if ((Test-Path -LiteralPath $redisExe) -and (Test-Path -LiteralPath $redisConfig)) {
            $redisStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            Start-Process -FilePath $redisExe -ArgumentList @('redis.conf') -WorkingDirectory $redisInstall -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $logRoot ('redis-'+$redisStamp+'.out.log')) `
                -RedirectStandardError (Join-Path $logRoot ('redis-'+$redisStamp+'.err.log')) | Out-Null
            for ($i = 0; $i -lt 20; $i++) {
                if (Test-LocalPort 6379) { break }
                Start-Sleep -Milliseconds 500
            }
        }
    }
}
if (!(Test-LocalPort 6379)) { throw 'Redis 尚未启动，请检查 hou/runtime/redis-install.txt 中的安装路径。' }

# 3. 已有生产实例时直接复用，避免重复占用端口
if (Test-Path -LiteralPath $pidFile) {
    $saved = (Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8).Trim().Split('|')
    if ($saved.Count -eq 2) {
        $savedPid = [int]$saved[0]; $savedPort = [int]$saved[1]
        if ((Get-Process -Id $savedPid -ErrorAction SilentlyContinue) -and (Test-NxzBackend $savedPort)) {
            $lan = Get-LanAddress
            Write-Host '农知行生产服务已经在运行。'
            Write-Host ("本机访问：  http://127.0.0.1:{0}" -f $savedPort)
            if ($lan) { Write-Host ("局域网访问：http://{0}:{1}" -f $lan, $savedPort) }
            exit 0
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}

# 4. 构建前端：dist 不存在、源码更新过或指定 -Rebuild 时执行 npm run build
$distIndex = Join-Path $frontendRoot 'dist\index.html'
$needsBuild = $Rebuild -or !(Test-Path -LiteralPath $distIndex)
if (!$needsBuild) {
    $distTime = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc
    $srcTime = (Get-ChildItem -LiteralPath (Join-Path $frontendRoot 'src') -Recurse -File |
        Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
    $entryTime = (Get-Item -LiteralPath (Join-Path $frontendRoot 'index.html')).LastWriteTimeUtc
    $pkgTime = (Get-Item -LiteralPath (Join-Path $frontendRoot 'package.json')).LastWriteTimeUtc
    if ($srcTime -gt $distTime -or $entryTime -gt $distTime -or $pkgTime -gt $distTime) { $needsBuild = $true }
}
if ($needsBuild) {
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (!$npm -and (Test-Path -LiteralPath 'C:\nvm4w\nodejs\npm.cmd')) { $npm = 'C:\nvm4w\nodejs\npm.cmd' }
    if (!$npm) { throw '未找到 npm，请安装 Node.js 并在 qian 目录执行 npm install。' }
    Write-Host '正在构建前端：npm run build ...'
    Push-Location $frontendRoot
    try {
        & $npm run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败，请查看上方错误信息。' }
    } finally { Pop-Location }
}

# 5. 选择 8080-8090 中空闲的端口
$port = 0
foreach ($candidate in 8080..8090) {
    if (!(Test-LocalPort $candidate)) { $port = $candidate; break }
}
if ($port -eq 0) { throw '8080-8090 均被占用，请先释放端口。' }

# 6. 以生产入口启动：同源托管 dist，监听所有网卡以便局域网访问
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonExe)) { throw '缺少后端虚拟环境，请查看 README 的安装说明。' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $logRoot ('backend-prod-' + $stamp + '.out.log')
$stderr = Join-Path $logRoot ('backend-prod-' + $stamp + '.err.log')
$process = Start-Process -FilePath $pythonExe `
    -ArgumentList @('-m','uvicorn','app.serve:app','--host','0.0.0.0','--port',"$port") `
    -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
"$($process.Id)|$port" | Set-Content -LiteralPath $pidFile -Encoding UTF8

# 7. 等待后端完成数据库迁移与初始化（首次冷启动最多 60 秒）
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Test-NxzBackend $port) { $ready = $true; break }
    if ($process.HasExited) { break }
    Start-Sleep -Milliseconds 1000
}
if (!$ready) {
    if (!$process.HasExited) { Stop-Process -Id $process.Id -Force }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $tail = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Tail 15) -join "`n" } else { '无错误日志' }
    throw ("后端启动失败，错误日志 hou\runtime\{0}:`n{1}" -f (Split-Path $stderr -Leaf), $tail)
}

# 8. 放行 Windows 防火墙端口（需要管理员权限；失败则只提示，不影响本机访问）
$ruleName = "农知行本地服务 $port"
& netsh advfirewall firewall show rule name="$ruleName" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$port profile=any | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "无法自动放行防火墙端口（需要管理员权限）。手机等局域网设备打不开时，请右键「放行局域网端口.cmd」选择「以管理员身份运行」；"
        Write-Warning ("或手动执行：netsh advfirewall firewall add rule name=`"$ruleName`" dir=in action=allow protocol=TCP localport=$port")
    }
}

# 9. 输出访问地址
$lanIp = Get-LanAddress
Write-Host ''
Write-Host '农知行已以生产模式启动（前端与接口同源，只需一个端口）。'
Write-Host ("本机访问：  http://127.0.0.1:{0}" -f $port)
if ($lanIp) { Write-Host ("局域网访问：http://{0}:{1}" -f $lanIp, $port) }
Write-Host ("接口文档：  http://127.0.0.1:{0}/docs" -f $port)
Write-Host ''
Write-Host '停止服务：双击「停止上线版.cmd」'
Write-Host '查看日志：hou\runtime\backend-prod-*.log'
Write-Host '安全提醒：默认演示密码 demo123 只适合本机演示；允许局域网访问前请在系统内修改账号密码，且不要放行 3306 端口。'
