# 一次性配置：允许局域网设备访问农知行的 8080 端口
# 必须右键「以管理员身份运行」，否则 Windows 会拒绝修改防火墙规则。
$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (!$isAdmin) {
    Write-Host '需要管理员权限。请关闭本窗口，右键「放行局域网端口.cmd」选择「以管理员身份运行」。'
    exit 1
}
$ruleName = '农知行本地服务 8080'
& netsh advfirewall firewall show rule name="$ruleName" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=8080 profile=any | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '添加防火墙规则失败。' }
    Write-Host '已放行 TCP 8080 端口。'
} else {
    Write-Host '防火墙规则已存在，无需重复添加。'
}
Write-Host '注意：只放行 8080，不要放行 MySQL 的 3306 或 Redis 的 6379。'
