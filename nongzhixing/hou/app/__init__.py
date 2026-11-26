# app 包入口：标记 hou/app 为 Python 包，本身不包含业务逻辑。
# 真正的 FastAPI 实例与路由在 main.py 中创建，启动命令为 uvicorn app.main:app。
