# =============================================================================
# serve.py —— 本机生产模式入口（无域名部署）
# 职责：在现有 FastAPI 应用之上托管 qian/dist，实现前后端同源，只需要一个端口。
# 说明：开发模式仍使用 `uvicorn app.main:app` + Vite（5173）；本文件不影响原入口。
# 启动：在 hou 目录执行
#       .venv\Scripts\python.exe -m uvicorn app.serve:app --host 0.0.0.0 --port 8080
# =============================================================================

# 导入路径工具：定位 qian/dist
from pathlib import Path
# 导入 FastAPI 异常：未知接口返回 JSON 404
from fastapi import HTTPException
# 导入 GZip 中间件：压缩前端静态资源，减少局域网传输体积
from fastapi.middleware.gzip import GZipMiddleware
# 导入文件响应：返回 index.html、静态文件
from fastapi.responses import FileResponse, JSONResponse
# 导入静态文件挂载：处理 /assets 下的构建产物
from fastapi.staticfiles import StaticFiles
# 导入现有应用：全部 /api 与 /_AMapService 路由已经注册在 app 上
from .main import app

# 前端构建目录：hou/app/serve.py -> hou -> 项目根 -> qian/dist
DIST = Path(__file__).resolve().parents[2] / "qian" / "dist"

# 启用 GZip：只压缩大于 1KB 的响应，接口小响应不受影响
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 前端已构建时托管静态页面；未构建时保留仅 API 模式，避免启动失败
if (DIST / "index.html").is_file():
    # 安装目录位于 dist 下，路径固定为 /assets
    if (DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    # SPA 回退路由：必须在所有接口和 /assets 挂载之后注册
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # 未知的接口路径保持 JSON 404，不能被 index.html 吞掉
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        # 地图安全代理路径同理
        if full_path == "_AMapService" or full_path.startswith("_AMapService/"):
            raise HTTPException(404, "代理路径不存在")
        # 解析真实路径，防止 ../ 路径穿越读到 dist 之外的文件
        target = (DIST / full_path).resolve()
        try:
            target.relative_to(DIST.resolve())
        except ValueError:
            raise HTTPException(404, "文件不存在")
        # 命中真实文件（favicon、manifest 等）直接返回
        if target.is_file():
            return FileResponse(target)
        # 其余路径交给 Vue Router（/trace/xxx、/login 等深层链接）
        return FileResponse(DIST / "index.html")
else:
    # 尚未构建前端时给出明确提示，API 和 /docs 仍然可用
    @app.get("/", include_in_schema=False)
    def dist_missing():
        return JSONResponse(
            {"service": "农知行 API", "hint": "前端尚未构建：在 qian 目录执行 npm run build 后重启服务"},
            status_code=503,
        )
