#!/usr/bin/env bash
# =============================================================================
# deploy-server.sh —— 农知行智慧农业平台 · 云服务器部署脚本
# 由 Gitee Go「主机部署」任务在目标服务器上以 root 身份执行。
# 用法：bash deploy/deploy-server.sh <制品解压目录>
# 制品目录内应包含 hou/、qian/dist/、deploy/。
# 部署只覆盖代码与前端产物，不动 hou/.env、hou/.venv、hou/runtime。
# =============================================================================
set -euo pipefail

APP_DIR=/opt/nongzhixing
SERVICE=nongzhixing
STAGE="${1:?用法: deploy-server.sh <制品解压目录>}"
LOG_DIR="$APP_DIR/.deploy"
LOG_FILE="$LOG_DIR/deploy.log"

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"; }
fail() { log "部署失败：$*"; exit 1; }

command -v rsync >/dev/null 2>&1 || fail "服务器未安装 rsync（dnf install -y rsync）"
[ -d "$STAGE/hou/app" ] || fail "制品缺少 hou/app"
[ -f "$STAGE/qian/dist/index.html" ] || fail "制品缺少 qian/dist/index.html"
[ -x "$APP_DIR/hou/.venv/bin/pip" ] || fail "服务器 venv 不存在：$APP_DIR/hou/.venv"

log "1/5 同步后端代码（保留 .env、.venv、runtime）"
rsync -a --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='runtime/' \
  --exclude='__pycache__/' \
  "$STAGE/hou/" "$APP_DIR/hou/"

log "2/5 同步前端构建产物"
rsync -a --delete "$STAGE/qian/dist/" "$APP_DIR/qian/dist/"

log "3/5 安装 Python 依赖"
"$APP_DIR/hou/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/hou/requirements.txt"

log "4/5 重启服务"
systemctl restart "$SERVICE"
sleep 3

log "5/5 健康检查"
code=""
for _ in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/api/health || true)
  [ "$code" = "200" ] && break
  sleep 2
done
[ "$code" = "200" ] || fail "健康检查未通过（/api/health 返回 ${code:-无响应}）"
systemctl is-active --quiet "$SERVICE" || fail "systemd 服务 $SERVICE 未运行"

log "部署完成：$(date '+%F %T')"
