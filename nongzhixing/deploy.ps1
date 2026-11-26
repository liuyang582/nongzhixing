param(
    # 跳过前端构建，直接使用已有的 qian/dist
    [switch]$SkipBuild,
    # 跳过 npm 依赖检查
    [switch]$SkipInstall
)
# =============================================================================
# deploy.ps1 —— 农知行智慧农业平台 · 本地一键部署
# 流程：构建前端 → 打包 → 上传 → 服务器执行 deploy/deploy-server.sh（重启 + 健康检查）
# 用法：双击 deploy.cmd，或在当前目录执行
#       powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
# 不依赖 Gitee，生产配置 .env/.venv/runtime 不会被覆盖。
# =============================================================================
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'qian'
$deployScript = Join-Path $projectRoot 'deploy\deploy-server.sh'

# 生产服务器信息不写入仓库：优先读取本地 deploy.local.ps1（已加入 .gitignore），
# 其次读取环境变量 NXZ_SERVER / NXZ_SSH_USER / NXZ_SSH_KEY。
$localConfig = Join-Path $projectRoot 'deploy.local.ps1'
if (Test-Path -LiteralPath $localConfig) { . $localConfig }
if (-not $server)  { $server  = if ($env:NXZ_SERVER)   { $env:NXZ_SERVER }   else { 'YOUR_SERVER_IP' } }
if (-not $sshUser) { $sshUser = if ($env:NXZ_SSH_USER) { $env:NXZ_SSH_USER } else { 'root' } }
if (-not $sshKey)  { $sshKey  = if ($env:NXZ_SSH_KEY)  { $env:NXZ_SSH_KEY }  else { Join-Path $HOME '.ssh/id_ed25519' } }
$remoteBundle = '/tmp/nxz-deploy.tar.gz'
$bundlePath = Join-Path $env:TEMP 'nxz-deploy.tar.gz'
# 显式使用 Windows 自带的 bsdtar，避免 Git Bash 的 GNU tar 把 C:\ 当成远程主机
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tarExe)) { $tarExe = 'tar' }

function Write-Step([string]$Message) {
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}
function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到命令 $Name。$Hint"
    }
}
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe 执行失败（退出码 $LASTEXITCODE）" }
}

# 0. 前置检查
Write-Step '0/5 检查环境'
if (-not (Test-Path -LiteralPath $sshKey)) { throw "SSH 密钥不存在：$sshKey" }
if (-not (Test-Path -LiteralPath $deployScript)) { throw "部署脚本不存在：$deployScript" }
if (-not (Get-Command $tarExe -ErrorAction SilentlyContinue)) { throw '未找到 tar.exe（Windows 10+ 自带）' }
Assert-Command 'ssh' '请在「设置 → 应用 → 可选功能」安装 OpenSSH 客户端'
Assert-Command 'scp' '请在「设置 → 应用 → 可选功能」安装 OpenSSH 客户端'
if (-not $SkipBuild) {
    Assert-Command 'npm.cmd' '请安装 Node.js 18+ 并加入 PATH'
}
$commit = ''
try { $commit = (& git -C $projectRoot rev-parse --short HEAD 2>$null) } catch { }
Write-Host ("服务器：{0}    代码版本：{1}" -f $server, $(if ($commit) { $commit } else { '未知' }))

# 1. 构建前端
if ($SkipBuild) {
    Write-Step '1/5 跳过前端构建'
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'dist\index.html'))) {
        throw 'qian\dist 不存在，无法跳过构建'
    }
} else {
    Write-Step '1/5 构建前端'
    Push-Location $frontendRoot
    try {
        if (-not $SkipInstall) {
            # 已安装时 npm 会快速校验并补齐依赖，package.json 变更也能同步
            Invoke-Checked 'npm.cmd' @('install', '--no-audit', '--no-fund')
        }
        Invoke-Checked 'npm.cmd' @('run', 'build')
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'dist\index.html'))) {
    throw '前端构建产物缺失：qian\dist\index.html'
}

# 2. 打包（与 Gitee Go 制品结构一致：hou + qian/dist + deploy）
Write-Step '2/5 打包'
if (Test-Path -LiteralPath $bundlePath) { Remove-Item -LiteralPath $bundlePath -Force }
Push-Location $projectRoot
try {
    Invoke-Checked $tarExe @(
        '-czf', $bundlePath,
        '--exclude=hou/.venv',
        '--exclude=hou/runtime',
        '--exclude=hou/.env',
        '--exclude=hou/.idea',
        '--exclude=hou/.pytest_cache',
        '--exclude=__pycache__',
        '--exclude=*.log',
        '--exclude=*.tsbuildinfo',
        'hou', 'qian/dist', 'deploy'
    )
} finally {
    Pop-Location
}
$sizeMB = [math]::Round((Get-Item -LiteralPath $bundlePath).Length / 1MB, 2)
Write-Host ("部署包：{0}（{1} MB）" -f $bundlePath, $sizeMB)

# 3. 上传
Write-Step '3/5 上传到服务器'
Invoke-Checked 'scp' @(
    '-i', $sshKey,
    '-o', 'ConnectTimeout=15',
    '-o', 'StrictHostKeyChecking=accept-new',
    $bundlePath,
    ("{0}@{1}:{2}" -f $sshUser, $server, $remoteBundle)
)

# 4. 服务器执行部署（同步代码 → pip → 重启 → 健康检查）
Write-Step '4/5 服务器部署'
$remoteScript = @'
set -e
STAGE=/root/nxz-deploy-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar -xzf /tmp/nxz-deploy.tar.gz -C "$STAGE"
bash "$STAGE/deploy/deploy-server.sh" "$STAGE"
'@
Invoke-Checked 'ssh' @(
    '-i', $sshKey,
    '-o', 'ConnectTimeout=15',
    '-o', 'StrictHostKeyChecking=accept-new',
    ("{0}@{1}" -f $sshUser, $server),
    $remoteScript
)

# 5. 公网验收
Write-Step '5/5 公网验收'
try {
    $response = Invoke-WebRequest -Uri ("http://{0}/" -f $server) -TimeoutSec 20 -UseBasicParsing
    Write-Host ("首页 HTTP {0}" -f $response.StatusCode) -ForegroundColor Green
    if ($response.StatusCode -ne 200) { throw "首页返回 $($response.StatusCode)" }
} catch {
    Write-Warning ("公网验收失败：{0}" -f $_.Exception.Message)
    throw
}

Write-Host "`n部署完成：http://$server" -ForegroundColor Green
