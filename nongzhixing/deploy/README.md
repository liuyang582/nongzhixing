# 部署说明

## 一键部署（推荐）

在 Windows 本地双击 `deploy.cmd`，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

流程：构建前端 → 打包 → 上传到目标服务器 → 执行 `deploy/deploy-server.sh` → 重启 systemd → 健康检查 → 公网验收。

服务器地址不写入仓库：在本地创建 `deploy.local.ps1`（已加入 `.gitignore`）并写入：

```powershell
$server  = '<服务器 IP 或域名>'
$sshUser = 'root'
$sshKey  = Join-Path $HOME '.ssh/<你的私钥>'
```

也可用环境变量 `NXZ_SERVER`、`NXZ_SSH_USER`、`NXZ_SSH_KEY` 覆盖。

可选参数：

| 参数 | 作用 |
| --- | --- |
| `-SkipBuild` | 不重新构建前端，直接上传已有的 `qian/dist`（只改后端时更快） |
| `-SkipInstall` | 不执行 `npm install`（依赖已就绪时） |

前置条件：本地 Node.js 18+、Windows 自带 tar/ssh/scp、具备可登录目标服务器（root）的 SSH 私钥，并已在 `deploy.local.ps1` 中配置服务器信息。

## 服务器端脚本

`deploy/deploy-server.sh` 由一键脚本或 Gitee Go 在服务器上执行：

1. 校验制品中有 `hou/app` 与 `qian/dist/index.html`；
2. `rsync` 同步后端与前端产物，保留 `hou/.env`、`hou/.venv`、`hou/runtime`；
3. `pip install -r hou/requirements.txt`；
4. `systemctl restart nongzhixing`；
5. 轮询 `http://127.0.0.1/api/health` 直到 200。

日志：`/opt/nongzhixing/.deploy/deploy.log`。

## 与 Gitee Go 的关系

仓库中保留了 `.workflow/nongzhixing-deploy.yml`，开通 Gitee Go 并接入主机组后，推送 `main` 也会自动部署。当前 Gitee 账号无法登录，所以暂以本地一键脚本为主；两者互不冲突，服务器脚本共用。
