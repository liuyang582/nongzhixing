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

## GitHub Actions 自动部署（推荐）

仓库根目录的 `.github/workflows/deploy.yml` 会在推送 `main`（且改动 `nongzhixing/` 下文件）时自动构建前端并部署；也可在 GitHub → **Actions → Deploy 农知行 → Run workflow** 手动触发。

首次使用需在 **Settings → Secrets and variables → Actions → New repository secret** 添加：

| Secret 名称 | 值 |
| --- | --- |
| `NXZ_HOST` | 服务器 IP 或域名 |
| `NXZ_SSH_USER` | `root` |
| `NXZ_SSH_KEY` | 服务器 SSH 私钥**全文**（如 `~/.ssh/id_ed25519_nxz` 的内容，含 `-----BEGIN/END-----` 两行） |

说明：

- 私钥只保存在 GitHub Secrets 中，公开仓库下也不会明文暴露；
- 服务器需已安装 `rsync`、存在 `/opt/nongzhixing/hou/.venv`，systemd 服务名 `nongzhixing`，且 22 端口可从公网访问；
- 部署逻辑复用 `deploy/deploy-server.sh`，保留 `hou/.env`、`hou/.venv`、`hou/runtime`，结束时检查 `/api/health`；
- 健康检查失败时 Actions 会标红，但代码已同步，需要修复后重跑或手动回滚；
- 本地一键部署（`deploy.ps1`）仍然可用，两者共用同一套服务器脚本。

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
