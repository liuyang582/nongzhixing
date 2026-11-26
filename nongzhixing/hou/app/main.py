# =============================================================================
# main.py —— FastAPI 应用入口与核心业务接口
# 职责：创建应用、注册中间件、实现认证/权限、通用记录 CRUD、库存销售、GIS 导入、
#       AI 分析任务、天气、附件、管理员与导出等接口。
# 结构：先定义公共依赖与工具函数，再按业务分组注册路由，最后挂载 features 和 amap。
# =============================================================================

# 导入 asyncio：预留异步能力（当前主要配合 FastAPI 的 async 路由）
import asyncio
# 导入 base64：解析前端上传的图片 data URL
import base64
# 导入 csv：导出通用记录的 CSV 台账
import csv
# 导入 io：内存字符串/字节流，用于导出文件
import io
# 导入 json：校验记录内容大小、写入 Redis
import json
# 导入日志：记录知识库语料导入等可降级失败
import logging
# 导入 math：数值字段有限性校验、演示环境数据生成
import math
# 导入 secrets：生成附件随机文件名
import secrets
# 导入 zipfile：解析 SHP 压缩包
import zipfile
# 导入异步上下文管理器：定义应用 lifespan
from contextlib import asynccontextmanager
# 导入日期时间类型：JWT 过期、记录时间、日期校验
from datetime import datetime, timedelta, date, timezone
# 再次导入 date 并命名为 CalendarDate：用于 Pydantic 请求体字段类型
from datetime import date as CalendarDate
# 导入 Decimal：库存与订单的精确金额计算
from decimal import Decimal
# 导入 Literal：限制分析类型与订单动作的取值
from typing import Literal
# 导入 PyJWT：签发和校验登录令牌
import jwt
# 导入 redis.asyncio：限流、缓存、事件流
import redis.asyncio as redis
# 导入 FastAPI 核心组件：应用、依赖、异常、上传文件、查询参数与请求对象
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query, Request
# 导入 CORS 中间件：允许前端开发服务器跨域访问
from fastapi.middleware.cors import CORSMiddleware
# 导入流式响应与文件响应：CSV 导出、附件下载
from fastapi.responses import StreamingResponse, FileResponse
# 导入 HTTP Bearer 认证：从 Authorization 头读取 JWT
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# 导入 Pydantic：请求体模型、字段约束与 ORM 配置
from pydantic import BaseModel, Field, ConfigDict
# 导入密码存储适配器：明文存储 + 旧哈希兼容
from .passwords import password_store
# 导入 SQLAlchemy 查询、统计、更新函数
from sqlalchemy import select, func, update
# 导入 SQLAlchemy 会话类型
from sqlalchemy.orm import Session
# 导入 pyproj：WGS84 大地测量面积计算与坐标系转换
from pyproj import Geod, CRS, Transformer
# 导入 pyshp：读取 SHP 文件
import shapefile
# 导入 httpx：调用 Open-Meteo 天气接口
import httpx
# 导入基础设施：配置、ORM 基类、引擎、会话、全部数据模型与运行时目录
from .core import settings, Base, engine, SessionLocal, get_db, User, Record, Stock, Order, Audit, AIJob, Attachment, KnowledgeDoc, runtime
# 导入业务模块目录与作物分组
from .catalog import MODULES, CROP_GROUPS
# 导入 LangGraph 编译后的 AI 工作流
from .ai import workflow
# 导入高德地图路由安装函数，并别名为 install_amap
from .amap import install as install_amap
# 导入知识库：语料导入、BM25 检索与专用接口安装函数
from .rag import seed_corpus, search as rag_search, install as install_rag

# 日志器：记录知识库导入等不影响主流程的异常
logger = logging.getLogger("nongzhixing.main")


# 创建 Redis 异步客户端：连接超时和读写超时均为 2 秒，避免 Redis 故障拖慢接口
cache = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
# HTTP Bearer 认证器：auto_error=False 表示没有令牌时由 current_user 自行返回 401
bearer = HTTPBearer(auto_error=False)

# 审计助手：向 nx_audits 表追加一条操作日志，调用方负责提交事务
def audit(db, user, action, detail=None):
    # actor_id 与 org 从当前用户取；detail 为空时存空字典
    db.add(Audit(actor_id=user.id, org=user.org, action=action, detail=detail or {}))

# 数据范围助手：给查询语句追加角色对应的隔离条件
def scope(stmt, model, user):
    # 经营主体只能看到本组织数据
    if user.role == "farmer":
        # 追加 org 条件
        return stmt.where(model.org == user.org)
    # 监管员只能看到本乡镇数据
    if user.role == "regulator":
        # 追加 district 条件
        return stmt.where(model.district == user.district)
    # 管理员不加限制（仅限管理员可访问的接口）
    return stmt

# 用户信息序列化：隐藏密码、token_version 等敏感字段
def user_info(u):
    # 返回前端需要的账号资料
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role, "org": u.org, "district": u.district, "active": u.active}

# 记录序列化：把 ORM 对象转换成前端可用的 JSON 结构
def record_info(r):
    # 时间统一转 ISO 字符串；demo 标记用于区分演示样本与真实录入
    return {"id": r.id, "module": r.module, "title": r.title, "status": r.status, "data": r.data, "demo": r.demo, "org": r.org, "version": r.version, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}

# 模块权限校验：检查模块是否存在、当前角色是否可读写
def authorize(module, user, write=False):
    # 从目录中取模块定义
    m = MODULES.get(module)
    # 模块不存在时返回 404
    if not m:
        # 抛出未找到异常
        raise HTTPException(404, "模块不存在")
    # 角色不在模块允许列表中时进入特殊判断
    if user.role not in m["roles"]:
        # 注释：监管员对部分生产资料只读；管理员不默认浏览经营隐私
        # 监管只读生产资料；系统管理员不默认浏览经营隐私。
        # 允许只读请求：监管员 + 指定生产资料模块；其余情况拒绝
        if not (not write and user.role == "regulator" and module in {"lands", "growth", "tasks", "environment", "alerts", "harvest"}):
            # 无权限时返回 403
            raise HTTPException(403, "没有此模块的权限")
    # 返回模块定义，供调用方读取字段配置
    return m

# 演示数据播种：首次启动时创建三个演示账号与示例台账
def seed(db):
    # 已存在用户时说明不是首次启动，直接返回，避免重复播种
    if db.scalar(select(func.count(User.id))):
        # 已有数据，不重复写入
        return
    # 创建三个演示账号：经营主体、监管员、管理员，密码统一取 DEMO_PASSWORD
    users = [User(username="farmer", password=password_store.encode(settings.demo_password), name="青禾合作社", role="farmer", org="青禾合作社", district="示范乡镇"),
             # 监管员账号：只看辖区数据
             User(username="regulator", password=password_store.encode(settings.demo_password), name="乡镇监管员", role="regulator", org="乡镇农业服务中心", district="示范乡镇"),
             # 管理员账号：用户、审计、资料审核
             User(username="admin", password=password_store.encode(settings.demo_password), name="系统管理员", role="admin", org="平台管理", district="示范乡镇")]
    # 批量加入会话并 flush，取得自增 ID 供记录关联
    db.add_all(users); db.flush()
    # 示例业务数据：地块、生长、任务、行情、农资、采收
    samples = {"lands": [("田块 A01", {"area": 18.5, "crop": "水稻", "ph": 6.5, "organic": 22, "note": "演示地块；无真实地图边界"}), ("01 号温室", {"area": 0.18, "crop": "番茄", "note": "演示温室"})],
               # 生长批次样本
               "growth": [("番茄种植批次 T-20260801", {"crop": "番茄", "plot": "01 号温室", "variety": "粉果番茄", "sow_date": "2026-08-01", "stage": "开花结果期", "harvest_date": "2026-10-25", "height": 86, "note": "模拟观察记录"})],
               # 农事任务样本
               "tasks": [("土壤湿度与管路检查", {"crop": "番茄", "plot": "01 号温室", "type": "灌溉检查", "date": date.today().isoformat(), "assignee": "管理员", "note": "先核实设备与现场情况"})],
               # 市场行情样本（明确标注为模拟价格）
               "market": [("番茄本地批发报价", {"crop": "番茄", "market": "本地市场演示样本", "region": "示范乡镇", "price": 6, "grade": "A", "type": "批发价", "date": date.today().isoformat(), "note": "模拟价格，不是实时行情"})],
               # 农资采购样本
               "inputs": [("种子采购记录", {"type": "种子", "batch": "S-01", "supplier": "演示供应商", "quantity": 80, "unit": "kg", "cost": 1600})],
               # 采收样本
               "harvest": [("前期番茄采收", {"crop": "番茄", "plot": "01 号温室", "batch": "T-20260701", "date": "2026-09-28", "quantity": 200, "grade": "A"})]}
    # 示例数据统一归属第一个演示账号
    farmer = users[0]
    # 逐模块、逐条写入通用记录表，全部标记 demo=True
    for key, entries in samples.items():
        # 遍历模块下的每条样本
        for title, data in entries:
            # 写入记录：org/district 与创建人一致，便于数据隔离演示
            db.add(Record(module=key, title=title, data=data, creator_id=farmer.id, org=farmer.org, district=farmer.district, demo=True))
    # 生成 24 小时模拟环境数据：温度/湿度/土壤湿度用正弦曲线模拟日变化
    for i in range(24):
        # 每条记录按小时设置 created_at，方便前端画 24 小时曲线
        db.add(Record(module="environment", title=f"模拟温室监测 {i:02d}:00", data={"plot": "01 号温室", "temperature": round(24+3*math.sin(i/4), 1), "humidity": round(65+8*math.cos(i/5), 1), "soil": round(45-i*.6, 1), "source": "模拟器"}, creator_id=farmer.id, org=farmer.org, district=farmer.district, demo=True, created_at=datetime.now().replace(hour=i, minute=0, second=0, microsecond=0)))
    # 写入两个库存批次，便于演示订单与销售核算
    db.add_all([Stock(crop="番茄", batch="H-0928", grade="A", quantity=200, reserved=0, source="T-20260701", org=farmer.org, district=farmer.district, demo=True), Stock(crop="番茄", batch="H-0930", grade="A", quantity=200, reserved=0, source="T-20260703", org=farmer.org, district=farmer.district, demo=True)])
    # 提交播种事务
    db.commit()

# 应用生命周期：启动时建表、迁移、播种、修复中断任务；关闭时释放 Redis
@asynccontextmanager
async def lifespan(app):
    # 根据 ORM 模型自动创建缺失的数据表（不会删除已有表）
    Base.metadata.create_all(engine)
    # 导入并执行增量迁移（当前负责 nx_users.token_version 列）
    from .features import migrate
    # 执行迁移 SQL
    migrate()
    # 打开一个数据库会话执行启动初始化
    with SessionLocal() as db:
        # 只有开启 SEED_DEMO 时才播种演示数据
        if settings.seed_demo:
            # 首次启动创建演示账号与样本
            seed(db)
        # 导入随项目打包的农业知识语料；已有条目按 doc_id 跳过，不覆盖人工修改
        try:
            # 执行幂等导入
            seed_corpus(db)
        except Exception:
            # 知识库导入失败只记录日志，不阻断业务服务启动
            logger.exception("知识库语料导入失败，服务继续启动")
        # 遍历三个内置演示账号，把历史 Argon2id 哈希迁移为明文
        for existing in db.scalars(select(User).where(User.username.in_(['farmer', 'regulator', 'admin']))).all():
            # 仅当存储值仍是 Argon2id 且密码能被 DEMO_PASSWORD 验证时才迁移
            if existing.password.startswith('$argon2id$') and password_store.verify(settings.demo_password, existing.password):
                # 改写为明文
                existing.password = password_store.encode(settings.demo_password)
                # 记录迁移审计
                audit(db, existing, '密码存储迁移为明文')
        # 服务重启后，把停留在“分析中”的 AI 任务标记为已中断，避免前端一直转圈
        db.execute(update(AIJob).where(AIJob.status == "分析中").values(status="已中断", result={"answer": "服务重启中断了分析，请重新提交；未执行生产操作。"}))
        # 提交初始化事务
        db.commit()
    # 应用运行期间把控制权交给 FastAPI
    yield
    # 应用关闭时释放 Redis 连接池
    await cache.aclose()

# 创建 FastAPI 应用：标题和版本会显示在 /docs 文档中
app = FastAPI(title="农知行 API", version="1.0.0", lifespan=lifespan)
# 注册 CORS 中间件：允许配置中的前端地址跨域访问，禁用 cookie 凭证，限制允许的方法和请求头
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

# 当前用户依赖：解析并校验 JWT，返回数据库中的用户对象
def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    # 没有 Authorization 头时返回 401
    if not credentials:
        # 提示先登录
        raise HTTPException(401, "请先登录")
    # 解码与校验可能失败，统一转换为 401
    try:
        # 使用 HS256 和全局密钥解码令牌
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        # 从 sub 取出用户 ID 并查询用户
        user = db.get(User, int(payload["sub"]))
    # 令牌过期、签名错误、字段缺失或 ID 非法都进入该分支
    except (jwt.PyJWTError, ValueError, KeyError):
        # 返回登录过期提示
        raise HTTPException(401, "登录已过期，请重新登录")
    # 用户不存在、被禁用，或令牌版本与当前账号不一致时拒绝
    if not user or not user.active or payload.get("ver", 0) != user.token_version:
        # 返回账号不可用
        raise HTTPException(401, "账号不可用")
    # 返回认证通过的用户对象
    return user

# 登录请求体：用户名和密码
class Login(BaseModel):
    # 用户名：1–64 个字符
    username: str = Field(min_length=1, max_length=64)
    # 密码：1–128 个字符
    password: str = Field(min_length=1, max_length=128)

# 登录接口：成功后签发 8 小时有效的 JWT
@app.post("/api/auth/login")
async def login(data: Login, request: Request, db: Session = Depends(get_db)):
    # 登录限流键：按客户端 IP 计数
    key = "nx:login:" + (request.client.host if request.client else "local")
    # Redis 故障不应阻断登录，因此单独捕获
    try:
        # 自增登录次数
        count = await cache.incr(key)
        # 第一次登录时设置 60 秒窗口
        if count == 1:
            # 设置过期时间
            await cache.expire(key, 60)
        # 每分钟超过 20 次拒绝，防止暴力破解
        if count > 20:
            # 返回 429
            raise HTTPException(429, "登录尝试过多，请一分钟后重试")
    # Redis 不可用时跳过限流，保证可用性
    except redis.RedisError:
        # 忽略限流异常
        pass
    # 按用户名查询用户
    user = db.scalar(select(User).where(User.username == data.username))
    # 无论用户是否存在都执行一次密码校验，避免通过响应时间枚举账号
    valid = password_store.verify(data.password, user.password) if user else password_store.verify(data.password, password_store.encode("dummy-not-a-password"))
    # 用户不存在、密码错误或账号被禁用时统一返回相同提示
    if not user or not valid or not user.active:
        # 返回 401
        raise HTTPException(401, "账号或密码不正确")
    # 历史 Argon2id 哈希在登录成功后迁移为明文
    if user.password.startswith('$argon2id$'):
        # 写入明文密码
        user.password = password_store.encode(data.password)
        # 记录迁移审计
        audit(db, user, '密码存储迁移为明文')
    # 签发 JWT：sub 为用户 ID，ver 为令牌版本，exp 为 8 小时后
    token = jwt.encode({"sub": str(user.id), "ver": user.token_version, "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, settings.jwt_secret, algorithm="HS256")
    # 记录登录审计并提交
    audit(db, user, "登录成功"); db.commit()
    # 返回令牌和用户资料
    return {"token": token, "user": user_info(user)}

# 当前用户资料接口
@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    # 直接序列化当前用户
    return user_info(user)

# 健康检查接口：前端启动时用于判断后端与 Redis 是否就绪
@app.get("/api/health")
async def health():
    # 默认 Redis 不可用
    redis_ok = False
    # 探测 Redis；异常时保持 False
    try:
        # ping 成功返回 True
        redis_ok = bool(await cache.ping())
    # Redis 故障不影响健康检查响应
    except redis.RedisError:
        # 忽略异常
        pass
    # 返回数据库类型、Redis 状态、模型配置情况与天气源
    return {"database": "MySQL" if engine.dialect.name == "mysql" else "SQLite（测试模式）", "redis": redis_ok, "model_configured": bool(settings.qwen_api_key), "model": settings.qwen_model, "weather": "Open-Meteo"}

# 模块列表接口：只返回当前角色可访问的模块
@app.get("/api/modules")
def modules(user=Depends(current_user)):
    # 按角色过滤模块目录
    return [m for m in MODULES.values() if user.role in m["roles"]]

# 作物分组接口：供前端作物选择使用
@app.get("/api/crops")
def crops(user=Depends(current_user)):
    # 把空格分隔的作物名拆成列表返回
    return [{"group": group, "names": names.split()} for group, names in CROP_GROUPS.items()]

# 通用记录新增/修改请求体
class RecordInput(BaseModel):
    # 标题：必填，最多 180 字
    title: str = Field(min_length=1, max_length=180)
    # 状态：默认“待处理”
    status: str = Field(default="待处理", max_length=32)
    # 业务字段：不同模块字段不同，由 validate_data 校验
    data: dict = Field(default_factory=dict)
    # 乐观锁版本号：修改时必须与数据库版本一致
    version: int | None = None

# 通用字段校验：按模块目录校验必填、类型、选项、关联关系与业务规则
def validate_data(module, body, user):
    # 先做模块权限检查（写操作）
    m = authorize(module, user, True)
    # 知识库是全局共享档案，使用专用接口维护，避免与经营台账混写
    if module == "knowledge":
        # 通用台账接口不再写入该模块
        raise HTTPException(422, "知识库请通过知识库专用接口维护")
    # 限制单条记录 JSON 体积，防止超大请求
    if len(json.dumps(body.data, ensure_ascii=False)) > 100_000:
        # 超过 100 KB 拒绝
        raise HTTPException(422, "记录内容过大")
    # 允许字段=模块字段 + 关联字段；地块额外允许 geometry/measured_area/attachments
    allowed = {f["key"] for f in m["fields"]} | ({"geometry", "measured_area", "attachments"} if module == "lands" else {"attachments", "plot_id", "growth_id", "ai_job_id"})
    # 告警模块额外允许规则、指标与环境记录 ID
    if module == "alerts":
        # 追加告警专用字段
        allowed |= {"rule_id", "metric", "environment_id"}
    # 出现目录之外的白名单字段时拒绝，防止注入未知字段
    if set(body.data) - allowed:
        # 返回未知字段错误
        raise HTTPException(422, "包含未知字段")
    # 逐字段执行类型与约束校验
    for f in m["fields"]:
        # 取出用户提交值
        value = body.data.get(f["key"])
        # 必填字段为空时拒绝
        if f["required"] and (value is None or value == ""):
            # 提示具体字段名
            raise HTTPException(422, f"请填写{f['label']}")
        # 数值字段：排除空值后校验
        if value not in (None, "") and f["type"] == "number":
            # 必须是有限数值，且排除布尔值（Python 中 bool 是 int 子类）
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                # 非法数值拒绝
                raise HTTPException(422, f"{f['label']}应为有效数值")
            # 除温度和海拔外，其他数值不允许为负
            if f["key"] not in {"temperature", "elevation"} and value < 0:
                # 负数拒绝
                raise HTTPException(422, f"{f['label']}不能为负数")
            # 百分比类字段不得超过 100
            if f["key"] in {"humidity", "soil", "moisture", "impurity"} and value > 100:
                # 超过 100 拒绝
                raise HTTPException(422, "百分比须在 0–100 之间")
        # 下拉字段必须命中选项集合
        if value not in (None, "") and f["type"] == "select" and value not in f["options"]:
            # 非法选项拒绝
            raise HTTPException(422, f"{f['label']}选项无效")
    # 地块模块校验天气定位经纬度范围（中国境内近似范围）
    if module == "lands":
        # 纬度 18–54，经度 73–135
        for key, lo, hi in (("latitude", 18, 54), ("longitude", 73, 135)):
            # 有值且超出范围时拒绝
            if body.data.get(key) not in (None, "") and not lo <= body.data[key] <= hi:
                # 返回范围错误
                raise HTTPException(422, "天气定位经纬度超出支持范围")
    # 检查地块/生长批次关联：跨模块数据必须真实存在且名称一致
    if body.data.get("plot_id") is not None:
        # 使用独立会话校验关联，避免污染主事务
        with SessionLocal() as links:
            # 取出并校验地块权限
            land = get_plot(body.data["plot_id"], user, links)
            # 记录中的地块名称必须与关联地块标题一致
            if body.data.get("plot") != land.title:
                # 不一致拒绝，保证追溯一致性
                raise HTTPException(422, "地块名称与关联地块不一致")
            # 若同时指定生长批次，校验它属于该地块
            if body.data.get("growth_id") is not None:
                # 调用生长记录校验
                get_growth(body.data["growth_id"], land, user, links)
    # 农事任务标记完成时必须填写执行结果
    if module == "tasks" and body.status == "已完成" and not str(body.data.get("note", "")).strip():
        # 缺少执行结果拒绝
        raise HTTPException(422, "完成任务前请填写执行结果")
    # 日期字段统一校验 ISO 格式
    for key in ("sow_date", "harvest_date", "date"):
        # 仅在提供了日期时校验
        if body.data.get(key):
            # 解析失败时返回格式提示
            try:
                # 按 YYYY-MM-DD 解析
                date.fromisoformat(body.data[key])
            # 非法日期或类型错误
            except (ValueError, TypeError):
                # 返回日期格式错误
                raise HTTPException(422, "日期格式应为 YYYY-MM-DD")
    # 生长模块：预计采收日期不能早于播种日期
    if module == "growth" and body.data.get("harvest_date") and body.data["harvest_date"] < body.data["sow_date"]:
        # 日期倒置拒绝
        raise HTTPException(422, "预计采收日期不能早于播种日期")
    # 农药资料标记已核验时的额外要求
    if module == "pesticides" and body.status == "已核验":
        # 必须提供 https 官方标签来源
        if not body.data.get("source", "").startswith("https://"):
            # 来源不合规拒绝
            raise HTTPException(422, "已核验产品需要官方标签来源链接")
        # 登记有效期必须存在且未过期
        try:
            # 有效期早于今天时拒绝
            if date.fromisoformat(body.data["expiry"]) < date.today():
                # 过期拒绝
                raise HTTPException(422, "登记已过期，不能标记为已核验")
        # 日期格式错误
        except ValueError:
            # 返回格式提示
            raise HTTPException(422, "登记有效期格式错误")
    # 校验通过，返回业务字段
    return body.data

# 通用记录列表接口：支持搜索、状态过滤与分页
@app.get("/api/records/{module}")
def records(module: str, q: str = "", status: str = "", page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), user=Depends(current_user), db: Session = Depends(get_db)):
    # 校验模块读取权限
    authorize(module, user)
    # 构造基础查询并追加数据范围
    stmt = scope(select(Record).where(Record.module == module), Record, user)
    # 有关键词时按标题模糊搜索，autoescape 防止通配符注入
    if q:
        # 追加标题包含条件
        stmt = stmt.where(Record.title.contains(q, autoescape=True))
    # 有状态过滤时追加状态条件
    if status:
        # 精确匹配状态
        stmt = stmt.where(Record.status == status)
    # 统计符合条件的总数（分页展示需要）
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    # 按 ID 倒序分页查询
    items = db.scalars(stmt.order_by(Record.id.desc()).offset((page-1)*size).limit(size)).all()
    # 返回列表与总数
    return {"items": [record_info(r) for r in items], "total": count}

# 环境记录事件：写入 Redis 最新值缓存与监控事件流
async def record_event(r):
    # 只有环境监测记录需要触发实时事件
    if r.module != "environment":
        # 其他模块直接返回
        return
    # Redis 故障不应影响记录保存
    try:
        # 缓存该组织该地块的最新环境记录，10 分钟过期
        await cache.set(f"nx:latest:{r.org}:{r.data.get('plot')}", json.dumps(record_info(r), ensure_ascii=False), ex=600)
        # 写入事件流，最多保留 1000 条，供监控消费
        await cache.xadd("nx:monitor-events", {"record_id": str(r.id), "org": r.org}, maxlen=1000)
    # Redis 不可用时静默忽略
    except redis.RedisError:
        # 不阻断主流程
        pass

# 新增记录接口
@app.post("/api/records/{module}")
async def create_record(module: str, body: RecordInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 统一校验字段与业务规则
    data = validate_data(module, body, user)
    # AI 来源字段只能通过人工确认接口产生，禁止直接伪造
    if data.get("ai_job_id") is not None:
        # 直接创建带 AI 来源的记录一律拒绝
        raise HTTPException(422, "AI 来源任务只能通过人工确认创建")
    # 地块记录带 GeoJSON 时自动计算面积（亩）
    if module == "lands" and data.get("geometry"):
        # 用 geodesic 面积覆盖 measured_area
        data = {**data, "measured_area": area_mu(data["geometry"])}
    # 创建记录：org/district 取当前用户，保证数据隔离
    r = Record(module=module, title=body.title.strip(), status=body.status, data=data, creator_id=user.id, org=user.org, district=user.district)
    # 写库、flush 取 ID、记审计并提交
    db.add(r); db.flush(); audit(db, user, "新增记录", {"module": module, "id": r.id}); db.commit()
    # 环境记录触发 Redis 事件
    await record_event(r)
    # 环境记录触发阈值预警评估
    if module == "environment":
        # 调用 features.py 注入的评估函数
        feature_environment_event(r, user, db)
    # 返回新记录
    return record_info(r)

# 修改记录接口：使用乐观锁防止并发覆盖
@app.put("/api/records/{module}/{record_id}")
async def edit_record(module: str, record_id: int, body: RecordInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 校验字段与业务规则
    data = validate_data(module, body, user)
    # 按 ID、模块和数据范围查询记录，并加行锁
    r = db.scalar(scope(select(Record).where(Record.id == record_id, Record.module == module).with_for_update(), Record, user))
    # 记录不存在或无权访问时返回 404
    if not r:
        # 未找到记录
        raise HTTPException(404, "记录不存在")
    # 前端提交的版本必须与数据库版本一致
    if body.version != r.version:
        # 版本冲突要求刷新
        raise HTTPException(409, "记录已更新，请刷新后重试")
    # 已建立的流程关联不能修改或移除，保证追溯链完整
    for key in ("plot_id", "growth_id", "ai_job_id", "rule_id", "metric", "environment_id"):
        # 原值存在且新值不同则拒绝
        if r.data.get(key) is not None and data.get(key) != r.data[key]:
            # 关联字段不可变更
            raise HTTPException(422, "已有流程关联不能修改或移除")
    # AI 来源同样不能伪造或篡改
    if data.get("ai_job_id") != r.data.get("ai_job_id"):
        # 禁止伪造 AI 来源
        raise HTTPException(422, "不能伪造 AI 来源")
    # AI 生成的农事任务只允许合法状态
    if r.data.get("ai_job_id") and body.status not in {"待处理", "进行中", "已完成", "已关闭"}:
        # 非法状态拒绝
        raise HTTPException(422, "农事任务状态无效")
    # 地块已有联动记录时不允许改名，避免追溯断链
    if module == "lands" and body.title.strip() != r.title and linked_records(r, user, db):
        # 要求保持名称
        raise HTTPException(409, "地块已有流程记录，请保持名称以便追溯")
    # 已入库的采收记录不可修改
    if module == "harvest":
        # 延迟导入 Trace，避免模块循环依赖
        from .core import Trace
        # 存在溯源记录说明已入库
        if db.scalar(select(Trace).where(Trace.harvest_id == r.id)):
            # 拒绝修改
            raise HTTPException(409, "已入库的采收记录不能修改，请保留溯源依据")
    # 保存修改前快照，写入审计
    old = {"title": r.title, "status": r.status, "data": r.data}
    # 地块边界变化时重新计算面积
    if module == "lands" and data.get("geometry"):
        # 覆盖测算面积
        data = {**data, "measured_area": area_mu(data["geometry"])}
    # 更新标题、状态与业务字段
    r.title, r.status, r.data = body.title.strip(), body.status, data
    # 乐观锁版本号加 1
    r.version += 1
    # 记录修改前后快照并提交
    audit(db, user, "修改记录", {"module": module, "id": r.id, "before": old, "after": {"title": r.title, "status": r.status, "data": r.data}}); db.commit()
    # 环境记录刷新 Redis 事件
    await record_event(r)
    # 环境记录重新评估阈值
    if module == "environment":
        # 调用预警评估
        feature_environment_event(r, user, db)
    # 返回更新后的记录
    return record_info(r)

# 删除记录接口：校验业务关联后物理删除并留审计快照
@app.delete("/api/records/{module}/{record_id}")
def delete_record(module: str, record_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 写权限校验
    authorize(module, user, True)
    # 按数据范围查询待删除记录
    r = db.scalar(scope(select(Record).where(Record.id == record_id, Record.module == module), Record, user))
    # 不存在时返回 404
    if not r:
        # 未找到记录
        raise HTTPException(404, "记录不存在")
    # 地块已有生长、环境、任务记录时禁止删除
    if module == "lands":
        # 查询可能引用该地块的三类记录
        linked = db.scalars(scope(select(Record).where(Record.module.in_(["growth", "environment", "tasks"])), Record, user)).all()
        # 任一记录引用该地块即拒绝
        if any(item.data.get("plot_id") == r.id for item in linked):
            # 提示保留档案
            raise HTTPException(409, "地块已有生长、环境或任务记录，请保留档案")
    # AI 流程任务只能关闭，不能删除
    if module == "tasks" and r.data.get("ai_job_id"):
        # 拒绝删除
        raise HTTPException(409, "AI 流程任务需保留追溯记录，可关闭而不能删除")
    # 生长批次已有生产记录或 AI 分析时禁止删除
    if module == "growth":
        # 查询引用该批次的农事、采收、告警记录
        linked_production = db.scalars(scope(select(Record).where(Record.module.in_(["tasks", "harvest", "alerts"])), Record, user)).all()
        # 存在引用则拒绝
        if any(item.data.get("growth_id") == r.id for item in linked_production):
            # 提示保留生产档案
            raise HTTPException(409, "生长批次已有农事、采收或预警记录，请保留生产档案")
        # 查询引用该批次的 AI 分析任务
        linked_jobs = db.scalars(scope(select(AIJob), AIJob, user)).all()
        # 存在引用则拒绝
        if any(j.result.get("growth_id") == r.id for j in linked_jobs):
            # 提示保留原始档案
            raise HTTPException(409, "生长记录已关联分析，请保留原始档案")
    # 已入库采收禁止删除
    if module == "harvest":
        # 延迟导入溯源模型
        from .core import Trace
        # 存在溯源记录说明已入库
        if db.scalar(select(Trace).where(Trace.harvest_id == r.id)):
            # 拒绝删除
            raise HTTPException(409, "已入库的采收记录不能删除")
    # 记录删除快照，保证日志可追溯
    audit(db, user, "删除记录", {"module": module, "id": r.id, "snapshot": record_info(r)})
    # 删除记录并提交
    db.delete(r); db.commit(); return {"ok": True}

# 数据看板接口：汇总各模块数量、环境曲线、库存、订单与销售
@app.get("/api/dashboard")
def dashboard(user=Depends(current_user), db: Session = Depends(get_db)):
    # 当前角色可见的模块 ID 列表
    keys = [m["id"] for m in MODULES.values() if user.role in m["roles"]]
    # 查询这些模块的记录，并追加数据范围
    stmt = scope(select(Record).where(Record.module.in_(keys)), Record, user)
    # 执行查询
    items = db.scalars(stmt).all()
    # 初始化每个模块的计数为 0
    counts = {k: 0 for k in keys}
    # 逐条累加模块计数
    for r in items:
        # 对应模块计数加 1
        counts[r.module] += 1
    # 知识库是全局共享档案，不在通用记录表内，单独统计启用条目数
    if "knowledge" in counts:
        # 管理员与普通角色看到同一份知识档案数量
        counts["knowledge"] = db.scalar(select(func.count(KnowledgeDoc.id)).where(KnowledgeDoc.status == "启用")) or 0
    # 按创建时间排序后取最近 48 条环境记录，用于画曲线
    env = [record_info(r) for r in sorted(items, key=lambda r: r.created_at) if r.module == "environment"][-48:]
    # 非管理员才查询库存（管理员无经营隐私权限）
    stocks = db.scalars(scope(select(Stock), Stock, user)).all() if user.role != "admin" else []
    # 非管理员才查询订单
    orders = db.scalars(scope(select(Order), Order, user)).all() if user.role != "admin" else []
    # 返回看板数据：计数、演示占比、环境曲线、最近更新、可用库存、待出库与销售额
    return {"counts": counts, "records": len(items), "demo_records": sum(r.demo for r in items), "environment": env, "recent": [record_info(r) for r in sorted(items, key=lambda r: r.updated_at, reverse=True)[:8]], "available_stock": float(sum(s.quantity-s.reserved for s in stocks)), "pending_orders": sum(o.status == "待出库" for o in orders), "sales": float(sum(o.quantity*o.price for o in orders if o.status == "已出库")), "users": db.scalar(select(func.count(User.id))) if user.role == "admin" else None}

# 库存新增请求体
class StockInput(BaseModel):
    # 农产品名称
    crop: str = Field(min_length=1, max_length=64)
    # 产品批号
    batch: str = Field(min_length=1, max_length=64)
    # 等级：默认 A
    grade: str = Field(default="A", max_length=20)
    # 入库数量：大于 0，最多 12 位、3 位小数
    quantity: Decimal = Field(gt=0, le=100000000, max_digits=12, decimal_places=3)
    # 来源说明：如采收记录编号
    source: str = Field(default="", max_length=180)

# 经营主体专用校验：库存、订单等经营操作只有 farmer 可用
def farmer_only(user):
    # 非经营主体返回 403
    if user.role != "farmer":
        # 提示仅经营主体可用
        raise HTTPException(403, "此操作仅经营主体可用")

# 库存列表接口
@app.get("/api/stocks")
def stocks(user=Depends(current_user), db: Session = Depends(get_db)):
    # 管理员不允许查看经营库存
    if user.role == "admin":
        # 返回 403
        raise HTTPException(403, "管理员无经营库存权限")
    # 返回本组织/辖区库存，数量转浮点便于前端展示
    return [{"id": s.id, "crop": s.crop, "batch": s.batch, "grade": s.grade, "quantity": float(s.quantity), "reserved": float(s.reserved), "available": float(s.quantity-s.reserved), "source": s.source, "demo": s.demo} for s in db.scalars(scope(select(Stock), Stock, user)).all()]

# 新增库存接口
@app.post("/api/stocks")
def add_stock(body: StockInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 仅经营主体可用
    farmer_only(user)
    # 创建库存批次并归属当前组织
    s = Stock(**body.model_dump(), org=user.org, district=user.district)
    # 写库、flush、记审计并提交
    db.add(s); db.flush(); audit(db, user, "农产品入库", {"id": s.id, "quantity": str(body.quantity)}); db.commit(); return {"id": s.id}

# 订单请求体
class OrderInput(BaseModel):
    # 关联库存批次 ID
    stock_id: int
    # 客户名称
    customer: str = Field(min_length=1, max_length=100)
    # 订单数量
    quantity: Decimal = Field(gt=0, le=100000000, max_digits=12, decimal_places=3)
    # 单价：允许 0，保留两位小数
    price: Decimal = Field(ge=0, le=10000000, max_digits=12, decimal_places=2)

# 订单列表接口
@app.get("/api/orders")
def orders(user=Depends(current_user), db: Session = Depends(get_db)):
    # 管理员无经营订单权限
    if user.role == "admin":
        # 返回 403
        raise HTTPException(403, "管理员无经营订单权限")
    # 按创建时间倒序返回订单及金额
    return [{"id": o.id, "stock_id": o.stock_id, "customer": o.customer, "quantity": float(o.quantity), "price": float(o.price), "amount": float(o.quantity*o.price), "status": o.status, "created_at": o.created_at.isoformat()} for o in db.scalars(scope(select(Order).order_by(Order.id.desc()), Order, user)).all()]

# 创建订单并预占库存
@app.post("/api/orders")
def add_order(body: OrderInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 仅经营主体可用
    farmer_only(user)
    # 查询本组织的库存批次并加行锁
    s = db.scalar(select(Stock).where(Stock.id == body.stock_id, Stock.org == user.org).with_for_update())
    # 库存不存在时返回 404
    if not s:
        # 提示批次不存在
        raise HTTPException(404, "库存批次不存在")
    # 可用量不足时返回 409
    if s.quantity-s.reserved < body.quantity:
        # 提示库存不足
        raise HTTPException(409, "可用库存不足")
    # 注释：条件更新即使数据库不支持行锁，也不会超额预占
    # 条件更新即使数据库不支持行锁也不会出现超额预占。
    # 用 SQL 条件更新预占量：仅当可用量仍足够时才成功
    result = db.execute(update(Stock).where(Stock.id == s.id, Stock.quantity-Stock.reserved >= body.quantity).values(reserved=Stock.reserved+body.quantity))
    # 影响行数不为 1 说明并发修改导致条件失效
    if result.rowcount != 1:
        # 要求刷新重试
        raise HTTPException(409, "库存发生变化，请刷新")
    # 创建订单并归属当前组织
    o = Order(**body.model_dump(), org=user.org, district=user.district)
    # 写库、flush、记审计并提交
    db.add(o); db.flush(); audit(db, user, "订单预占", {"id": o.id, "stock_id": s.id}); db.commit(); return {"id": o.id}

# 订单出库 / 取消接口
@app.post("/api/orders/{order_id}/{action}")
def order_action(order_id: int, action: Literal["ship", "cancel"], user=Depends(current_user), db: Session = Depends(get_db)):
    # 仅经营主体可用
    farmer_only(user)
    # 查询本组织订单并加行锁
    o = db.scalar(select(Order).where(Order.id == order_id, Order.org == user.org).with_for_update())
    # 订单不存在时返回 404
    if not o:
        # 提示不存在
        raise HTTPException(404, "订单不存在")
    # 只有待出库订单可以操作，防止重复出库/取消
    if o.status != "待出库":
        # 返回冲突
        raise HTTPException(409, "订单已处理，不能重复操作")
    # 查询关联库存并加行锁
    s = db.scalar(select(Stock).where(Stock.id == o.stock_id, Stock.org == user.org).with_for_update())
    # 库存缺失、预占量或总量不足时要求核查
    if not s or s.reserved < o.quantity or s.quantity < o.quantity:
        # 返回库存不一致
        raise HTTPException(409, "库存与订单不一致，请核查")
    # 条件更新订单状态，只有仍为待出库时才成功（先抢占订单）
    claim = db.execute(update(Order).where(Order.id == o.id, Order.status == "待出库").values(status="已出库" if action == "ship" else "已取消"))
    # 未抢到说明已被其他请求处理
    if claim.rowcount != 1:
        # 返回已处理
        raise HTTPException(409, "订单已被处理")
    # 释放预占；出库时同时扣减总库存，取消时只释放预占
    db.execute(update(Stock).where(Stock.id == s.id).values(reserved=Stock.reserved-o.quantity, quantity=Stock.quantity-o.quantity if action == "ship" else Stock.quantity))
    # 记录出库或取消审计并提交
    audit(db, user, "订单出库" if action == "ship" else "订单取消", {"id": o.id}); db.commit(); return {"ok": True}

# 地块面积计算：GeoJSON 坐标按 WGS84 椭球计算，返回亩
def area_mu(geometry):
    # 只接受 Polygon / MultiPolygon
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        # 其他几何类型拒绝
        raise HTTPException(422, "只支持 Polygon / MultiPolygon 地块")
    # 统一成多边形列表：Polygon 包一层，MultiPolygon 直接用
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    # 使用 WGS84 椭球做大地测量
    geod = Geod(ellps="WGS84"); total = 0
    # 逐多边形、逐环累加面积
    try:
        # 遍历每个多边形
        for polygon in polygons:
            # 空多边形无效
            if not polygon:
                # 抛出异常进入统一错误处理
                raise ValueError()
            # 遍历外环与内环；外环取正、内环取负，实现孔洞扣减
            for i, ring in enumerate(polygon):
                # 环至少 4 个点、首尾闭合，且经纬度在合法范围
                if len(ring) < 4 or ring[0] != ring[-1] or any(not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in ring):
                    # 非法环
                    raise ValueError()
                # 计算该环的大地面积（平方米）和周长
                area, _ = geod.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])
                # 外环累加，内环扣减
                total += abs(area) * (1 if i == 0 else -1)
        # 总面积必须为正，否则说明坐标或环方向异常
        if total <= 0:
            # 非法面积
            raise ValueError()
    # 任一解析/类型/索引异常都视为坐标无效
    except (ValueError, KeyError, TypeError, IndexError):
        # 返回统一错误提示
        raise HTTPException(422, "地块坐标无效，必须为 WGS84 经度纬度闭合边界")
    # 1 亩 = 2000/3 平方米；保留 3 位小数
    return round(total / (2000/3), 3)

# GIS 边界导入接口：支持 GeoJSON 或含 shp/shx/dbf/prj 的 ZIP
@app.post("/api/gis/import")
async def import_gis(file: UploadFile = File(...), user=Depends(current_user)):
    # 仅经营主体可导入
    farmer_only(user)
    # 最多读取 10 MB + 1 字节，用于判断是否超限
    content = await file.read(10*1024*1024+1)
    # 超过 10 MB 返回 413
    if len(content) > 10*1024*1024:
        # 文件过大
        raise HTTPException(413, "边界文件不能超过 10 MB")
    # 解析文件内容
    try:
        # GeoJSON 直接按 JSON 解析
        if (file.filename or "").lower().endswith((".json", ".geojson")):
            # 解析 JSON
            geo = json.loads(content)
        # ZIP 按 SHP 包处理
        elif (file.filename or "").lower().endswith(".zip"):
            # 以内存方式打开压缩包
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                # 解压后总大小超过 30 MB 视为压缩炸弹
                if sum(x.file_size for x in archive.infolist()) > 30*1024*1024:
                    # 抛出异常进入统一处理
                    raise ValueError()
                # 读取包内文件名列表，准备按扩展名匹配
                names = archive.namelist(); parts = {}
                # 必须各有一个 shp/shx/dbf/prj
                for ext in ("shp", "shx", "dbf", "prj"):
                    # 查找对应扩展名的文件
                    matches = [n for n in names if n.lower().endswith("."+ext)]
                    # 数量不为 1 时拒绝
                    if len(matches) != 1:
                        # 返回缺文件提示
                        raise HTTPException(422, "ZIP 必须含一组 shp/shx/dbf/prj 文件")
                    # 读取该文件字节
                    parts[ext] = archive.read(matches[0])
                # 从 prj 文件解析源坐标系
                crs = CRS.from_wkt(parts["prj"].decode("utf-8-sig")); transform = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
                # 用 pyshp 读取 SHP/SHX/DBF
                reader = shapefile.Reader(shp=io.BytesIO(parts["shp"]), shx=io.BytesIO(parts["shx"]), dbf=io.BytesIO(parts["dbf"]), encoding="utf-8", encodingErrors="replace")
                # 转换后的要素列表
                features = []
                # 递归转换坐标：任意深度的嵌套坐标数组都转换到 WGS84
                def convert(coords):
                    # 最内层是 [x, y] 数字对
                    if isinstance(coords[0], (float, int)):
                        # 使用 pyproj 转换并返回列表
                        return list(transform.transform(coords[0], coords[1]))
                    # 其他层级递归处理
                    return [convert(c) for c in coords]
                # 逐图形转换
                for shape in reader.shapes():
                    # 取 GeoJSON 接口的几何结构
                    geometry = shape.__geo_interface__; geometry["coordinates"] = convert(geometry["coordinates"])
                    # 包装成标准 Feature
                    features.append({"type": "Feature", "geometry": geometry, "properties": {}})
                # 组装 FeatureCollection
                geo = {"type": "FeatureCollection", "features": features}
        # 其他扩展名不支持
        else:
            # 返回格式提示
            raise HTTPException(422, "支持 GeoJSON 或含 SHP 的 ZIP")
        # 统一取出要素列表：FeatureCollection 用 features，单要素包一层
        features = geo.get("features", []) if geo.get("type") == "FeatureCollection" else [geo]
        # 单次导入 1–100 个地块
        if not 1 <= len(features) <= 100:
            # 数量不合法
            raise HTTPException(422, "每次导入 1–100 个地块")
        # 逐个计算面积并返回几何与面积
        return [{"geometry": f["geometry"], "area": area_mu(f["geometry"])} for f in features]
    # 已抛出的 HTTP 异常直接向上传递
    except HTTPException:
        # 保持原状态码与提示
        raise
    # 其他解析异常统一转为 422
    except Exception:
        # 返回格式、编码或坐标系错误提示
        raise HTTPException(422, "边界文件无法解析，请核对格式、编码与坐标系")

# AI 分析请求体
class AIInput(BaseModel):
    # 用户问题：2–4000 字
    question: str = Field(min_length=2, max_length=4000)
    # 分析类型：普通问答 / 病虫害诊断 / 农事 / 种植 / 行情
    kind: Literal["chat", "diagnosis", "farm", "planting", "market"] = "chat"
    # 作物名称
    crop: str = Field(default="", max_length=64)
    # 图片 data URL：最大约 14 MB 字符
    image: str = Field(default="", max_length=14_000_000)
    # 关联地块 ID
    plot_id: int | None = Field(default=None, gt=0)
    # 关联生长记录 ID
    growth_id: int | None = Field(default=None, gt=0)

# AI 分析接口：读取授权数据、调用工作流、保存任务与人工确认状态
@app.post("/api/ai/analyze")
async def analyze(body: AIInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 未配置模型密钥时明确返回 503
    if not settings.qwen_api_key:
        # 提示配置千问密钥
        raise HTTPException(503, "请配置千问密钥")
    # 按 ID 取地块并校验权限
    land = get_plot(body.plot_id, user, db) if body.plot_id else None
    # 若指定生长记录，校验它属于该地块
    growth = get_growth(body.growth_id, land, user, db) if body.growth_id else None
    # 照片诊断必须同时具备照片、地块和生长记录
    if body.kind == "diagnosis" and (not body.image or not land or not growth):
        # 返回缺少条件的提示
        raise HTTPException(422, "照片分析需要关联地块、生长记录并上传照片")
    # 种植管理类分析只对经营主体开放
    if land and user.role != "farmer":
        # 其他角色拒绝
        raise HTTPException(403, "种植管理分析仅对经营主体开放")
    # 图片格式与大小校验
    if body.image:
        # 只接受 JPEG/PNG/WebP 的 data URL，拒绝远程 URL
        if not body.image.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")):
            # 返回格式提示
            raise HTTPException(422, "只接受本地图片编码，不接受任意远程图片 URL")
        # 解码并做魔数校验
        try:
            # 严格 base64 解码
            raw = base64.b64decode(body.image.split(",", 1)[1], validate=True)
            # 文件头与 data URL 类型必须匹配，且解码后不超过 10 MB
            valid_image = (raw.startswith(b"\x89PNG\r\n\x1a\n") and ";" in body.image and body.image.startswith("data:image/png;")) or (raw.startswith(b"\xff\xd8\xff") and body.image.startswith("data:image/jpeg;")) or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP" and body.image.startswith("data:image/webp;"))
            # 格式不符或体积超限都视为无效
            if not valid_image or len(raw) > 10*1024*1024:
                # 抛出异常进入统一处理
                raise ValueError()
        # 解码失败或校验失败
        except ValueError:
            # 返回无效提示
            raise HTTPException(422, "图片格式无效或超过 10 MB")
    # AI 调用限流：每用户每分钟最多 6 次
    try:
        # 限流键按用户 ID 区分
        key = f"nx:ai-limit:{user.id}"
        # 自增计数
        n = await cache.incr(key)
        # 首次调用设置 60 秒窗口
        if n == 1:
            # 设置过期
            await cache.expire(key, 60)
        # 超过 6 次拒绝
        if n > 6:
            # 返回 429
            raise HTTPException(429, "AI 分析每分钟最多 6 次，请稍后再试")
    # Redis 故障时跳过限流
    except redis.RedisError:
        # 忽略异常
        pass
    # 注释：只向模型提供本角色可读的业务资料，不发送用户、合同和联系方式
    # 只向模型提供本角色可读取的业务资料；不发送用户、合同和联系方式。
    # 按角色限定可提供给模型的模块
    allowed = {"growth", "environment", "tasks", "market"} if user.role == "farmer" else {"regional-pests", "verification"} if user.role == "regulator" else {"dictionary"}
    # 有关联地块时，组装与该地块相关的上下文
    if land:
        # 读取地块联动的生长、环境、任务记录
        context = linked_records(land, user, db)
        # 只保留：最新生长记录、最近 8 条环境记录、该批次最近 3 条任务
        context = ([growth] if growth else [r for r in context if r.module == "growth"][-1:]) + [r for r in context if r.module == "environment"][-8:] + [r for r in context if r.module == "tasks" and (not growth or r.data.get("growth_id") == growth.id)][-3:]
    # 无地块时，按角色取最近 12 条可读记录
    else:
        # 查询并限定数据范围
        context = db.scalars(scope(select(Record).where(Record.module.in_(allowed)).order_by(Record.id.desc()).limit(12), Record, user)).all()
    # 结果快照：记录本次分析关联的地块与批次，便于复用与审计
    snapshot = {"plot_id": land.id if land else None, "plot": land.title if land else "", "growth_id": growth.id if growth else None}
    # 作物优先取生长记录，其次取用户输入
    snapshot["crop"] = str(growth.data.get("crop", "")) if growth else body.crop
    # 有关联地块时补充天气与地块摘要
    if land:
        # 天气/定位失败不应阻断 AI 分析
        try:
            # 取地块经纬度
            lat, lon = plot_location(land)
            # 调用天气服务
            snapshot["weather"] = await weather(latitude=lat, longitude=lon, user=user)
        # 天气异常记录为不可用原因
        except HTTPException as exc:
            # 标记天气不可用并附原因
            snapshot["weather"] = {"unavailable": True, "reason": exc.detail}
        # 地块摘要排除合同、附件与几何边界等敏感/大字段
        snapshot["land"] = {"id": land.id, "title": land.title, "demo": land.demo, "data": {k:v for k,v in land.data.items() if k not in {"contract", "attachments", "geometry"}}}
    # 记录上下文快照
    snapshot["records"] = [record_info(r) for r in context]
    # 检索内部知识库：问题与作物作为查询，取前 5 条作为可引用依据
    knowledge = rag_search(db, f"{body.question} {snapshot['crop']}", snapshot["crop"], "", "", 5)
    # 检索结果先写入快照，模型失败时也能看到本次依据
    snapshot["knowledge"] = knowledge
    # 有图片时保存为附件，供人工确认任务引用
    if body.image:
        # 根据 data URL 选择扩展名
        ext = ".png" if body.image.startswith("data:image/png") else ".jpg" if body.image.startswith("data:image/jpeg") else ".webp"
        # 生成 36 位随机文件名
        name = secrets.token_hex(18) + ext
        # 上传目录
        directory = runtime / "uploads"
        # 确保目录存在
        directory.mkdir(exist_ok=True)
        # 写入图片文件
        (directory/name).write_bytes(raw)
        # 创建附件记录并归属当前组织
        photo = Attachment(name="田间分析照片" + ext, path=name, size=len(raw), org=user.org, district=user.district)
        # 写库并获得自增 ID
        db.add(photo); db.flush()
        # 快照记录照片 ID，人工确认时挂到任务附件
        snapshot["photo_id"] = photo.id
    # 创建 AI 任务：状态默认“分析中”，保存问题、快照和步骤
    job = AIJob(org=user.org, district=user.district, creator_id=user.id, kind=body.kind, question=body.question, result=snapshot, steps=["读取授权数据"])
    # 写库提交，保证即使模型调用失败也有任务记录
    db.add(job); db.commit()
    # 调用 LangGraph 工作流
    try:
        # 传入请求、作物与上下文；有地块时追加地块与天气摘要
        state = await workflow.ainvoke({**body.model_dump(), "crop": snapshot["crop"], "knowledge": knowledge, "context": [{"module": r.module, "title": r.title, "data": r.data, "demo": r.demo} for r in context] + ([{"selected_land": snapshot["land"], "weather": snapshot["weather"]}] if land else [])})
        # 需要人工确认的分析标记为“待确认”，其余标记“已完成”
        job.status = "待确认" if state["review"] == "待人工确认" else "已完成"
        # 保存回答、模型名、业务记录 ID 与知识库引用；sources 保持原含义不破坏前端
        job.result = {**snapshot, "answer": state["answer"], "model": settings.qwen_model, "sources": [r.id for r in context], "citations": knowledge}
        # 保存工作流步骤
        job.steps = state["steps"]
        # 记录分析完成审计并提交
        audit(db, user, "AI 分析完成", {"job_id": job.id, "kind": body.kind}); db.commit()
    # 模型调用失败：保存失败结果并返回 502，绝不伪造答案
    except Exception:
        # 任务标记失败并写明原因
        job.status = "失败"; job.result = {**snapshot, "answer": "模型调用失败，请检查接口、模型权限、额度和网络；未执行任何生产操作。"}; db.commit()
        # 向上返回 502
        raise HTTPException(502, job.result["answer"])
    # 返回任务信息
    return job_info(job)

# AI 任务序列化：隐藏组织等内部字段
def job_info(j):
    # 返回前端需要的任务 ID、类型、问题、状态、结果、步骤、关联任务与时间
    return {"id": j.id, "kind": j.kind, "question": j.question, "status": j.status, "result": j.result, "steps": j.steps, "task_id": j.task_id, "created_at": j.created_at.isoformat()}

# AI 任务列表接口
@app.get("/api/ai/jobs")
def jobs(user=Depends(current_user), db: Session = Depends(get_db)):
    # 按数据范围取最近 50 条任务并序列化
    return [job_info(j) for j in db.scalars(scope(select(AIJob).order_by(AIJob.id.desc()).limit(50), AIJob, user)).all()]

# 人工确认请求体
class ConfirmInput(BaseModel):
    # 任务标题：为空时使用默认标题
    title: str = Field(default="", max_length=180)
    # 执行人：为空时使用当前用户名
    assignee: str = Field(default="", max_length=64)
    # 计划日期：为空时使用今天
    date: CalendarDate | None = None
    # 人工意见 / 执行说明
    note: str = Field(default="", max_length=6000)

# 人工确认 AI 建议：生成可追溯的农事任务
@app.post("/api/ai/jobs/{job_id}/confirm")
def confirm(job_id: int, body: ConfirmInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 仅经营主体可确认
    farmer_only(user)
    # 查询本组织任务并加行锁，防止重复确认
    job = db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.org == user.org).with_for_update())
    # 任务不存在返回 404
    if not job:
        # 提示不存在
        raise HTTPException(404, "建议不存在")
    # 只有“待确认”任务可以确认
    if job.status != "待确认":
        # 已处理或无需确认
        raise HTTPException(409, "建议已处理或不需要确认")
    # 条件更新抢占任务，避免并发重复生成任务
    claim = db.execute(update(AIJob).where(AIJob.id == job.id, AIJob.status == "待确认").values(status="已确认"))
    # 未抢占成功说明已被处理
    if claim.rowcount != 1:
        # 返回冲突
        raise HTTPException(409, "建议已被处理")
    # 生成农事任务：继承 AI 快照中的作物、地块、批次、照片，并记录 ai_job_id 供追溯
    task = Record(module="tasks", title=body.title.strip() or f"AI 建议人工复核 #{job.id}", data={"crop": job.result.get("crop", ""), "plot_id": job.result.get("plot_id"), "plot": job.result.get("plot", ""), "growth_id": job.result.get("growth_id"), "ai_job_id": job.id, "type": "巡检", "assignee": body.assignee.strip() or user.name, "date": (body.date or date.today()).isoformat(), "note": body.note.strip() or "人工确认后现场巡检，请在完成时填写实际执行结果。", "attachments": [job.result["photo_id"]] if job.result.get("photo_id") else []}, creator_id=user.id, org=user.org, district=user.district)
    # 写库并回填任务 ID
    db.add(task); db.flush(); job.task_id = task.id
    # 记录确认审计并提交
    audit(db, user, "确认 AI 建议", {"job_id": job.id, "task_id": task.id}); db.commit()
    # 返回新任务 ID
    return {"task_id": task.id}

# 通用记录 CSV 导出
@app.get("/api/records/{module}/export/csv")
def export(module: str, user=Depends(current_user), db: Session = Depends(get_db)):
    # 校验模块权限
    m = authorize(module, user)
    # 查询该模块全部可见记录
    rows = db.scalars(scope(select(Record).where(Record.module == module), Record, user)).all()
    # 用内存字符串缓冲区写 CSV
    buf = io.StringIO(); writer = csv.writer(buf)
    # 表头：固定列 + 模块字段中文名
    writer.writerow(["标题", "状态", "演示数据", "更新时间"]+[f["label"] for f in m["fields"]])
    # 单元格清洗：以公式符号开头的值加单引号，防止 CSV 公式注入
    def safe_cell(v):
        # 空值转空字符串
        s = str(v or "")
        # 公式开头加前缀单引号
        return "'"+s if s.startswith(("=", "+", "-", "@", "\t", "\r")) else s
    # 写入每条记录
    for r in rows:
        # 固定列 + 各字段值
        writer.writerow([safe_cell(r.title), r.status, "是" if r.demo else "否", r.updated_at.isoformat()]+[safe_cell(r.data.get(f["key"])) for f in m["fields"]])
    # 记录导出审计并提交
    audit(db, user, "导出记录", {"module": module, "count": len(rows)}); db.commit()
    # 加 UTF-8 BOM，保证 Excel 打开中文不乱码
    return StreamingResponse(iter([("﻿"+buf.getvalue()).encode("utf-8")]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{module}.csv"'})

# 管理员：用户列表
@app.get("/api/admin/users")
def user_list(user=Depends(current_user), db: Session = Depends(get_db)):
    # 非管理员拒绝
    if user.role != "admin":
        # 返回 403
        raise HTTPException(403, "仅管理员可用")
    # 返回全部用户资料（不含密码）
    return [user_info(u) for u in db.scalars(select(User)).all()]

# 管理员：新增用户请求体
class UserInput(BaseModel):
    # 登录名：3–64 位，仅字母数字下划线短横线
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    # 展示名称
    name: str = Field(min_length=1, max_length=64)
    # 初始密码：至少 8 位
    password: str = Field(min_length=8, max_length=128)
    # 角色：三种固定角色
    role: Literal["farmer", "regulator", "admin"]
    # 所属组织
    org: str = Field(min_length=1, max_length=64)
    # 所属乡镇
    district: str = Field(default="示范乡镇", max_length=64)

# 管理员：新增用户
@app.post("/api/admin/users")
def new_user(body: UserInput, user=Depends(current_user), db: Session = Depends(get_db)):
    # 非管理员拒绝
    if user.role != "admin":
        # 返回 403
        raise HTTPException(403, "仅管理员可用")
    # 登录名重复时返回 409
    if db.scalar(select(User).where(User.username == body.username)):
        # 提示账号已存在
        raise HTTPException(409, "账号已存在")
    # 创建用户，密码按项目要求存明文
    u = User(**{**body.model_dump(), "password": password_store.encode(body.password)})
    # 写库、记审计并提交
    db.add(u); db.flush(); audit(db, user, "新增账号", {"id": u.id, "role": u.role}); db.commit(); return user_info(u)

# 管理员：启用 / 禁用账号
@app.post("/api/admin/users/{user_id}/toggle")
def toggle_user(user_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 非管理员拒绝
    if user.role != "admin":
        # 返回 403
        raise HTTPException(403, "仅管理员可用")
    # 不允许禁用自己
    if user_id == user.id:
        # 返回 422
        raise HTTPException(422, "不能禁用当前登录账号")
    # 查询目标用户
    u = db.get(User, user_id)
    # 不存在返回 404
    if not u:
        # 提示不存在
        raise HTTPException(404, "账号不存在")
    # 切换启用状态并记录审计
    u.active = not u.active; audit(db, user, "更改账号状态", {"id": u.id, "active": u.active}); db.commit(); return user_info(u)

# 管理员：操作日志
@app.get("/api/admin/audit")
def audits(user=Depends(current_user), db: Session = Depends(get_db)):
    # 非管理员拒绝
    if user.role != "admin":
        # 返回 403
        raise HTTPException(403, "仅管理员可用")
    # 返回最近 200 条审计日志
    return [{"id": a.id, "actor": a.actor_id, "org": a.org, "action": a.action, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(200)).all()]

# 附件列表
@app.get("/api/files")
def files(user=Depends(current_user), db: Session = Depends(get_db)):
    # 按数据范围返回最近 200 个附件元数据
    return [{"id": f.id, "name": f.name, "size": f.size, "org": f.org, "created_at": f.created_at.isoformat()} for f in db.scalars(scope(select(Attachment).order_by(Attachment.id.desc()).limit(200), Attachment, user)).all()]

# 附件上传
@app.post("/api/files")
async def upload(file: UploadFile = File(...), user=Depends(current_user), db: Session = Depends(get_db)):
    # 只取文件名最后一段，防止路径穿越；限制 255 字符
    name = (file.filename or "附件").replace("\\", "/").split("/")[-1][:255]
    # 取小写扩展名
    ext = "." + name.rsplit(".", 1)[-1].lower()
    # 只允许白名单类型
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".xlsx", ".docx", ".zip"}:
        # 返回类型提示
        raise HTTPException(422, "仅支持文档、图片与 ZIP 附件")
    # 读取最多 10 MB + 1 字节
    content = await file.read(10*1024*1024+1)
    # 空文件或超限拒绝
    if not content or len(content) > 10*1024*1024:
        # 返回大小提示
        raise HTTPException(413, "附件不能为空且不得超过 10 MB")
    # 上传目录
    directory = runtime / "uploads"; directory.mkdir(exist_ok=True)
    # 随机存储文件名，保留扩展名
    path = secrets.token_hex(20)+ext
    # 写入磁盘
    (directory/path).write_bytes(content)
    # 创建附件记录
    f = Attachment(name=name, path=path, size=len(content), org=user.org, district=user.district)
    # 写库、记审计并提交
    db.add(f); db.flush(); audit(db, user, "上传附件", {"id": f.id, "name": name}); db.commit()
    # 返回附件 ID 与名称
    return {"id": f.id, "name": f.name}

# 附件下载
@app.get("/api/files/{file_id}")
def get_file(file_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 按数据范围查询附件
    f = db.scalar(scope(select(Attachment).where(Attachment.id == file_id), Attachment, user))
    # 记录不存在或文件已丢失时返回 404
    if not f or not (runtime/"uploads"/f.path).exists():
        # 提示不存在
        raise HTTPException(404, "附件不存在")
    # 记录下载审计并提交
    audit(db, user, "下载附件", {"id": f.id}); db.commit()
    # 返回文件流，下载时还原原始文件名
    return FileResponse(runtime/"uploads"/f.path, filename=f.name, media_type="application/octet-stream")

# 天气接口：使用 Open-Meteo 免费服务，结果缓存 10 分钟
@app.get("/api/weather")
async def weather(latitude: float = Query(30.27, ge=18, le=54), longitude: float = Query(120.15, ge=73, le=135), user=Depends(current_user)):
    # 缓存键按经纬度三位小数归一化，复用相邻位置结果
    key = f"nx:weather:{latitude:.3f}:{longitude:.3f}"
    # 先查缓存
    try:
        # 读取缓存字符串
        stored = await cache.get(key)
        # 命中时标记 cached=True 并返回
        if stored:
            # JSON 反序列化后合并缓存标记
            return {**json.loads(stored), "cached": True}
    # Redis 故障时直接走实时查询
    except redis.RedisError:
        # 忽略缓存异常
        pass
    # 调用 Open-Meteo
    try:
        # 12 秒超时的异步客户端
        async with httpx.AsyncClient(timeout=12) as client:
            # 请求当前天气与未来 7 天预报
            response = await client.get("https://api.open-meteo.com/v1/forecast", params={"latitude":latitude,"longitude":longitude,"current":"temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m", "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone":"Asia/Shanghai", "forecast_days":7})
            # 非 2xx 抛出异常
            response.raise_for_status(); value=response.json()
        # 组装返回结构，标注数据来源与抓取时间
        result = {"source":"Open-Meteo", "source_url":"https://open-meteo.com/", "fetched_at":datetime.now().isoformat(), "cached":False, "latitude":latitude,"longitude":longitude,"current":value["current"],"daily":value["daily"]}
        # 写入 10 分钟缓存
        try:
            # 序列化后缓存
            await cache.set(key,json.dumps(result),ex=600)
        # 缓存失败不影响返回
        except redis.RedisError:
            # 忽略
            pass
        # 返回实时结果
        return result
    # 任何网络/解析异常都明确报错，不返回模拟天气
    except Exception:
        # 返回 502
        raise HTTPException(502,"天气服务暂不可用；没有返回模拟天气，请稍后重试")

# 公共知识资料：只返回已核验的基础资料
@app.get("/api/knowledge")
def knowledge(crop: str = "", user=Depends(current_user), db: Session = Depends(get_db)):
    # 注释：公共资料不含经营主体私有台账
    # 已审核发布的公共资料，不携带经营主体私有台账。
    # 查询状态为“已核验”的基础资料，最多 200 条
    records = db.scalars(select(Record).where(Record.module == "dictionary", Record.status == "已核验").limit(200)).all()
    # 可按作物过滤后返回
    return [record_info(r) for r in records if not crop or r.data.get("crop") == crop]

# 农药候选资料：只返回管理员核验且未过期、作物与防治对象精确匹配的产品
@app.get("/api/pesticide-candidates")
def candidates(crop: str, target: str, user=Depends(current_user), db: Session = Depends(get_db)):
    # 查询已核验的农药资料，最多 500 条
    records = db.scalars(select(Record).where(Record.module == "pesticides", Record.status == "已核验").limit(500)).all()
    # 有效候选列表
    valid = []
    # 逐条筛选
    for r in records:
        # 作物或防治对象不匹配则跳过
        if r.data.get("crop") != crop or r.data.get("target") != target:
            # 继续下一条
            continue
        # 登记有效期必须未过期
        try:
            # 未过期则加入候选
            if date.fromisoformat(r.data.get("expiry", "")) >= date.today():
                # 追加候选
                valid.append(record_info(r))
        # 日期格式错误视为无效资料
        except ValueError:
            # 跳过
            continue
    # 返回候选与使用提示
    return {"items":valid,"note":"仅返回管理员人工核验且未过期的精确作物 / 防治对象匹配产品；使用前仍须核对标签和当地禁限用规定。"}


# 地块读取助手：按 ID 查询并校验访问权限
def get_plot(plot_id, user, db):
    # 编号必须是整数，且排除布尔值
    if isinstance(plot_id, bool) or not isinstance(plot_id, int):
        # 返回编号格式错误
        raise HTTPException(422, "地块编号应为整数")
    # 校验地块模块读取权限
    authorize("lands", user)
    # 按 ID、模块和数据范围查询地块
    land = db.scalar(scope(select(Record).where(Record.id == plot_id, Record.module == "lands"), Record, user))
    # 不存在或无权访问时返回 404
    if not land:
        # 统一提示，避免泄露其他组织数据是否存在
        raise HTTPException(404, "地块不存在或没有访问权限")
    # 返回地块记录
    return land

# 生长记录读取助手：必须属于指定地块
def get_growth(growth_id, land, user, db):
    # 没有地块时无法校验生长记录归属
    if not land:
        # 返回提示
        raise HTTPException(422, "请选择生长记录所属地块")
    # 按 ID、模块和数据范围查询生长记录
    growth = db.scalar(scope(select(Record).where(Record.id == growth_id, Record.module == "growth"), Record, user))
    # 记录不存在或不属于该地块时拒绝
    if not growth or growth.data.get("plot_id") != land.id:
        # 返回归属错误
        raise HTTPException(422, "生长记录不属于所选地块")
    # 返回生长记录
    return growth

# 地块定位助手：读取经纬度用于天气查询
def plot_location(land):
    # 从业务字段取经纬度
    lat, lon = land.data.get("latitude"), land.data.get("longitude")
    # 任一缺失时提示补充
    if lat is None or lon is None:
        # 返回 422
        raise HTTPException(422, "请补充地块经纬度后查询天气")
    # 转成浮点数返回
    return float(lat), float(lon)

# 地块联动记录：取生长、环境、任务三类记录并按时间排序
def linked_records(land, user, db):
    # 查询三类记录并追加数据范围
    rows = db.scalars(scope(select(Record).where(Record.module.in_(["growth", "environment", "tasks"])).order_by(Record.created_at, Record.id), Record, user)).all()
    # 只保留 plot_id 指向该地块的记录
    return [r for r in rows if r.data.get("plot_id") == land.id]

# 种植流程接口：返回地块、生长、环境、任务与 AI 分析的完整视图
@app.get("/api/plots/{plot_id}/flow")
def plot_flow(plot_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 校验地块权限
    land = get_plot(plot_id, user, db)
    # 取联动记录
    rows = linked_records(land, user, db)
    # 取本组织全部 AI 任务（按新到旧）
    analyses = db.scalars(scope(select(AIJob).order_by(AIJob.id.desc()), AIJob, user)).all()
    # 返回按模块分组的数据；环境只取最近 48 条，AI 只取该地块且最多 50 条
    return {"land": record_info(land), "growth": [record_info(r) for r in rows if r.module == "growth"], "environment": [record_info(r) for r in rows if r.module == "environment"][-48:], "tasks": [record_info(r) for r in rows if r.module == "tasks"], "jobs": [job_info(j) for j in analyses if j.result.get("plot_id") == land.id][:50]}

# 地块天气接口：按地块坐标查询天气
@app.get("/api/plots/{plot_id}/weather")
async def plot_weather(plot_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 校验地块权限
    land = get_plot(plot_id, user, db)
    # 读取经纬度
    lat, lon = plot_location(land)
    # 复用天气接口
    return await weather(latitude=lat, longitude=lon, user=user)

# 驳回 AI 建议：不生成农事任务
@app.post("/api/ai/jobs/{job_id}/reject")
def reject_job(job_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    # 仅经营主体可用
    farmer_only(user)
    # 查询本组织任务并加行锁
    job = db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.org == user.org).with_for_update())
    # 不存在返回 404
    if not job:
        # 提示不存在
        raise HTTPException(404, "建议不存在")
    # 条件更新为“已驳回”，只有待确认任务能成功
    claim = db.execute(update(AIJob).where(AIJob.id == job.id, AIJob.status == "待确认").values(status="已驳回"))
    # 未成功说明已处理
    if claim.rowcount != 1:
        # 返回冲突
        raise HTTPException(409, "建议已处理或不需要确认")
    # 记录驳回审计并提交
    audit(db, user, "驳回 AI 建议", {"job_id": job.id}); db.commit()
    # 返回成功
    return {"ok": True}

# 安装扩展功能：features.py 负责环境规则、核算、溯源、报表等接口
from .features import install as install_features
# 传入 app 和当前模块的全局命名空间，让 features 复用公共依赖
install_features(app, globals())
# 安装高德地图代理与配置接口
install_amap(app, current_user, lambda: cache)
# 安装内部 RAG 知识库的浏览、检索与管理员维护接口
install_rag(app, globals())
