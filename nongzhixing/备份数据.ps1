$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $projectRoot ("backups\" + $stamp)
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# 1. 导出 MySQL 数据库（需要输入 root 密码）
$dumpExe = 'D:\phpstudy_pro\Extensions\MySQL8.0.12\bin\mysqldump.exe'
if (!(Test-Path -LiteralPath $dumpExe)) {
    $dumpExe = (Get-Command mysqldump.exe -ErrorAction SilentlyContinue).Source
}
if (!$dumpExe) { throw '未找到 mysqldump，请确认 MySQL 安装位置。' }
$sqlFile = Join-Path $outDir 'nongzhixing.sql'
Write-Host '正在导出数据库 nongzhixing，请按提示输入 MySQL root 密码...'
& $dumpExe -u root -p --single-transaction --default-character-set=utf8mb4 --result-file="$sqlFile" nongzhixing
if ($LASTEXITCODE -ne 0) { throw '数据库导出失败，已中止备份。' }

# 2. 备份上传附件、JWT 密钥和 .env（内含密钥，注意妥善保管）
$runtime = Join-Path $projectRoot 'hou\runtime'
if (Test-Path -LiteralPath (Join-Path $runtime 'uploads')) {
    Copy-Item -LiteralPath (Join-Path $runtime 'uploads') -Destination (Join-Path $outDir 'uploads') -Recurse -Force
}
if (Test-Path -LiteralPath (Join-Path $runtime '.jwt-secret')) {
    Copy-Item -LiteralPath (Join-Path $runtime '.jwt-secret') -Destination $outDir -Force
}
$envFile = Join-Path $projectRoot 'hou\.env'
if (Test-Path -LiteralPath $envFile) {
    Copy-Item -LiteralPath $envFile -Destination (Join-Path $outDir 'hou.env.bak') -Force
}

Write-Host ("备份完成：{0}" -f $outDir)
Write-Host '包含：数据库 SQL、上传附件、JWT 密钥、.env。请把整个目录另存到移动硬盘或网盘，不要提交 Git。'
