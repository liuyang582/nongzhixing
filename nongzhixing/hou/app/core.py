# =============================================================================
# core.py —— 后端基础设施层
# 职责：读取 .env 配置、初始化 MySQL 连接、定义全部 ORM 数据表、提供请求级数据库会话。
# 说明：本文件不包含任何业务接口，只被 main.py、features.py、ai.py 等模块共享引用。
# =============================================================================

# 导入日期时间类型：用作数据表 created_at / updated_at 字段的类型与默认值
from datetime import datetime
# 导入路径工具：用于计算项目根目录和拼接 .env、runtime 路径
from pathlib import Path
# 导入安全随机数模块：用于自动生成 JWT 默认密钥
import secrets
# 导入 pydantic-settings：把 .env 中的配置项自动映射为 Python 属性
from pydantic_settings import BaseSettings, SettingsConfigDict
# 导入 SQLAlchemy 的引擎与字段类型：用于创建数据库连接和声明业务数据表
from sqlalchemy import create_engine, String, Text, DateTime, JSON, Numeric, ForeignKey, Boolean, Integer
# 导入 ORM 基类、字段映射函数和会话工厂
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# 项目根目录：core.py 位于 hou/app/ 下，parents[1] 即 hou 目录
ROOT = Path(__file__).resolve().parents[1]

# Settings 配置类：属性名与 hou/.env 中的变量名一一对应（大小写不敏感）
class Settings(BaseSettings):
    # 配置来源：hou/.env；extra="ignore" 忽略未声明的变量；使用 UTF-8 读取
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_file_encoding="utf-8")
    # 数据库连接串：默认本地 MySQL 8 的 nongzhixing 库
    database_url: str = "mysql+pymysql://root:YOUR_PASSWORD@127.0.0.1:3306/nongzhixing?charset=utf8mb4"
    # Redis 连接串：使用 1 号库，避免与其他项目共用 0 号库造成键冲突
    redis_url: str = "redis://127.0.0.1:6379/1"
    # JWT 签名密钥：留空时启动阶段自动生成并持久化到 runtime/.jwt-secret
    jwt_secret: str = ""
    # 演示账号统一密码：首次启动播种 farmer / regulator / admin 时使用
    demo_password: str = "demo123"
    # 是否播种演示数据：默认开启，方便答辩和首次体验
    seed_demo: bool = True
    # 千问模型接口地址：使用 OpenAI 兼容协议
    qwen_base_url: str = "https://maas.qianwenaiapi.com/compatible-mode/v1"
    # 千问模型名称：多模态模型，用于照片初筛与文本问答
    qwen_model: str = "qwen3.5-omni-plus"
    # 千问 API Key：为空时 AI 分析接口会返回 503，不会伪造结果
    qwen_api_key: str = ""
    # 天气服务 Key：当前使用免 Key 的 Open-Meteo，保留该字段兼容旧配置
    weather_api_key: str = ""
    # 默认天气定位城市编码：101210101 对应浙江省杭州市
    weather_location: str = "101210101"
    # 高德 JS API Key：由 /api/amap/config 返回给前端加载地图
    amap_key: str = ""
    # 高德安全密钥：只在后端 /_AMapService 代理中使用，绝不返回前端
    amap_security_code: str = ""
    # 允许跨域访问的前端地址：多个地址用英文逗号分隔
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # RAG 语料路径：留空时读取随项目打包的 app/data/agri_knowledge_v1.jsonl
    rag_corpus_path: str = ""
    # 对外访问地址：用于生成溯源二维码；留空时按当前请求的访问地址自动生成
    public_base_url: str = ""

# 实例化配置对象：应用启动时读取一次 .env，各模块共享同一份配置
settings = Settings()
# 运行目录：存放上传文件、日志、自动生成的 JWT 密钥等运行时产物
runtime = ROOT / "runtime"
# 创建运行目录；exist_ok=True 表示目录已存在时不报错
runtime.mkdir(exist_ok=True)
# 如果 .env 中没有配置 JWT_SECRET，则自动生成一个并落盘
if not settings.jwt_secret:
    # 默认密钥文件路径：hou/runtime/.jwt-secret
    secret_path = runtime / ".jwt-secret"
    # 首次启动且文件不存在时，生成 48 字节的 URL 安全随机串
    if not secret_path.exists():
        # 将随机密钥写入文件，保证重启后令牌仍然有效
        secret_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    # 从文件读回密钥并去掉首尾空白
    settings.jwt_secret = secret_path.read_text(encoding="utf-8").strip()
# 密钥长度校验：短于 32 个字符会削弱 JWT 安全性，直接拒绝启动
if len(settings.jwt_secret) < 32:
    # 抛出运行时异常，uvicorn 会中止启动并输出错误
    raise RuntimeError("JWT_SECRET 至少需要 32 个字符")

# 创建数据库引擎：pool_pre_ping 在取连接前先探活，避免 MySQL 空闲断连
engine = create_engine(settings.database_url, pool_pre_ping=True,
                       # SQLite 需要关闭线程检查；MySQL 则设置 5 秒连接超时
                       connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {"connect_timeout": 5})
# 会话工厂：expire_on_commit=False 让提交后仍能读取对象属性，避免延迟加载报错
SessionLocal = sessionmaker(engine, expire_on_commit=False)

# ORM 声明基类：下面所有数据表模型都继承它
class Base(DeclarativeBase):
    # 基类不需要额外逻辑，仅作为 SQLAlchemy 声明注册点
    pass

# 用户表：保存登录账号、密码、角色、所属组织、辖区与令牌版本
class User(Base):
    # 表名统一使用 nx_ 前缀，避免与其他系统的表冲突
    __tablename__ = "nx_users"
    # 主键：自增用户 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 登录名：唯一约束，注册时限制为字母、数字、下划线、短横线
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # 密码：按项目要求存明文；历史 Argon2id 哈希在登录成功后自动迁移
    password: Mapped[str] = mapped_column(String(255))
    # 展示名称：如“青禾合作社”“乡镇监管员”
    name: Mapped[str] = mapped_column(String(64))
    # 角色：farmer=经营主体，regulator=监管员，admin=管理员
    role: Mapped[str] = mapped_column(String(20))
    # 所属组织：经营主体按 org 隔离数据
    org: Mapped[str] = mapped_column(String(64))
    # 所属乡镇：监管员按 district 查看辖区数据
    district: Mapped[str] = mapped_column(String(64), default="示范乡镇")
    # 账号启用状态：管理员可禁用账号，被禁用后旧令牌立即失效
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 令牌版本：修改密码或重置密码时加 1，使旧 JWT 全部失效
    token_version: Mapped[int] = mapped_column(Integer, default=0)

# 通用业务记录表：地块、生长、任务、环境、市场等 20 多个模块共用这一张表
class Record(Base):
    # 表名：nx_records
    __tablename__ = "nx_records"
    # 主键：自增记录 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 模块标识：lands / growth / tasks / environment 等，建索引便于按模块查询
    module: Mapped[str] = mapped_column(String(32), index=True)
    # 记录标题：如“田块 A01”“番茄种植批次 T-20260801”
    title: Mapped[str] = mapped_column(String(180))
    # 业务状态：待处理 / 进行中 / 已完成 / 已关闭等
    status: Mapped[str] = mapped_column(String(32), default="待处理")
    # 所属组织：数据权限隔离的第一维度
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇：监管员按辖区查看数据的隔离维度
    district: Mapped[str] = mapped_column(String(64), index=True)
    # 创建人 ID：外键关联 nx_users.id
    creator_id: Mapped[int] = mapped_column(ForeignKey("nx_users.id"))
    # 业务字段：使用 MySQL JSON 列，不同模块存放不同字段，避免为每个模块建表
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    # 演示数据标记：True 表示系统播种样本，False 表示用户真实录入
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # 乐观锁版本号：每次修改加 1，前端提交旧版本时返回 409 防止覆盖
    version: Mapped[int] = mapped_column(Integer, default=1)
    # 创建时间：默认取当前时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 更新时间：任何字段修改时 SQLAlchemy 自动刷新
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

# 库存表：保存采收入库后的农产品批次与可售数量
class Stock(Base):
    # 表名：nx_stocks
    __tablename__ = "nx_stocks"
    # 主键：自增库存 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 农产品名称：如番茄、水稻
    crop: Mapped[str] = mapped_column(String(64))
    # 产品批号：用于销售与溯源对应
    batch: Mapped[str] = mapped_column(String(64))
    # 等级：A / B / 未分级
    grade: Mapped[str] = mapped_column(String(20), default="A")
    # 总库存量：Numeric(12,3) 保留三位小数，单位 kg
    quantity: Mapped[float] = mapped_column(Numeric(12, 3))
    # 已预占量：下单但尚未出库的数量
    reserved: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    # 所属组织：经营主体数据隔离
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇：监管数据范围
    district: Mapped[str] = mapped_column(String(64))
    # 来源：如 harvest:12 表示来自第 12 条采收记录
    source: Mapped[str] = mapped_column(String(180), default="")
    # 演示数据标记
    demo: Mapped[bool] = mapped_column(Boolean, default=False)

# 销售订单表：记录客户下单、预占库存、出库或取消
class Order(Base):
    # 表名：nx_orders
    __tablename__ = "nx_orders"
    # 主键：自增订单 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 关联库存批次：外键 nx_stocks.id
    stock_id: Mapped[int] = mapped_column(ForeignKey("nx_stocks.id"))
    # 客户名称
    customer: Mapped[str] = mapped_column(String(100))
    # 订单数量：kg
    quantity: Mapped[float] = mapped_column(Numeric(12, 3))
    # 单价：元/kg，保留两位小数
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    # 订单状态：待出库 / 已出库 / 已取消
    status: Mapped[str] = mapped_column(String(20), default="待出库")
    # 所属组织
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇
    district: Mapped[str] = mapped_column(String(64))
    # 下单时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

# 操作审计表：记录登录、增删改、导出、AI 确认等关键动作
class Audit(Base):
    # 表名：nx_audits
    __tablename__ = "nx_audits"
    # 主键：自增日志 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 操作人 ID：不设外键，保证用户删除后日志仍可保留
    actor_id: Mapped[int] = mapped_column(Integer)
    # 操作人所属组织
    org: Mapped[str] = mapped_column(String(64))
    # 动作名称：如“登录成功”“新增记录”“导出正式报表”
    action: Mapped[str] = mapped_column(String(100))
    # 动作详情：JSON 保存模块、记录 ID、修改前后快照等
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    # 操作时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

# AI 分析任务表：保存问题、授权快照、分析状态、结果与人工确认关联
class AIJob(Base):
    # 表名：nx_ai_jobs
    __tablename__ = "nx_ai_jobs"
    # 主键：自增任务 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 所属组织：AI 结果也遵循数据隔离
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇
    district: Mapped[str] = mapped_column(String(64))
    # 发起人 ID
    creator_id: Mapped[int] = mapped_column(Integer)
    # 状态：分析中 / 待确认 / 已完成 / 已确认 / 已驳回 / 失败 / 已中断
    status: Mapped[str] = mapped_column(String(32), default="分析中")
    # 分析类型：chat / diagnosis / farm / planting / market
    kind: Mapped[str] = mapped_column(String(32))
    # 用户问题原文
    question: Mapped[str] = mapped_column(String(4000))
    # 结果快照：包含地块、生长记录、天气、上下文、模型回答等
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # 工作流步骤：如“读取授权数据”“千问多模态分析”“待人工确认”
    steps: Mapped[list] = mapped_column(JSON, default=list)
    # 人工确认后生成的农事任务 ID：未生成时为空
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 任务创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

# 附件表：保存用户上传的文档、图片、ZIP 等文件元数据
class Attachment(Base):
    # 表名：nx_attachments
    __tablename__ = "nx_attachments"
    # 主键：自增附件 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 原始文件名：下载时还原给用户
    name: Mapped[str] = mapped_column(String(255))
    # 磁盘存储文件名：随机 40 位十六进制 + 扩展名，防止路径穿越
    path: Mapped[str] = mapped_column(String(100))
    # 文件大小：字节
    size: Mapped[int] = mapped_column(Integer)
    # 所属组织
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇
    district: Mapped[str] = mapped_column(String(64))
    # 上传时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

# 知识库表：保存全局共享的农技知识档案，供 BM25 检索与惠农服务知识库页面使用
class KnowledgeDoc(Base):
    # 表名：nx_knowledge_docs；知识库不按组织隔离，所有登录角色共享检索
    __tablename__ = "nx_knowledge_docs"
    # 主键：自增档案 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 语料编号：如 A1-01；管理员新增条目使用 KB- 前缀，唯一索引保证幂等导入
    doc_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 条目标题
    title: Mapped[str] = mapped_column(String(200))
    # 一级分类：语料 A–G，分别对应基础农艺、作物栽培、植物保护等
    domain_l1: Mapped[str] = mapped_column(String(8), default="")
    # 二级分类：如 土壤物理性质、水稻栽培
    domain_l2: Mapped[str] = mapped_column(String(64), default="")
    # 适用作物、地区、生育期、农事环节：JSON 数组，支持通用/全国标记
    crop: Mapped[list] = mapped_column(JSON, default=list)
    region: Mapped[list] = mapped_column(JSON, default=list)
    stage: Mapped[list] = mapped_column(JSON, default=list)
    operation: Mapped[list] = mapped_column(JSON, default=list)
    # 检索关键词与用户常见问法：BM25 的高权重字段
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    queries: Mapped[list] = mapped_column(JSON, default=list)
    # 正文：Markdown 文本，接口返回原文，前端按纯文本展示
    content: Mapped[str] = mapped_column(Text, default="")
    # 来源：标准号、官方文件或资料名称
    source: Mapped[str] = mapped_column(String(500), default="")
    # 时效、权威、置信与风险等级：用于展示和检索提示
    stability: Mapped[str] = mapped_column(String(16), default="稳定")
    authority: Mapped[str] = mapped_column(String(4), default="B")
    confidence: Mapped[str] = mapped_column(String(16), default="")
    risk_level: Mapped[str] = mapped_column(String(8), default="低")
    # 版本号：语料升级与人工修改时更新
    version: Mapped[str] = mapped_column(String(16), default="v1.0")
    # 是否来自随项目打包的语料：用于在管理页标注来源
    corpus: Mapped[bool] = mapped_column(Boolean, default=False)
    # 启用状态：停用后不参与检索
    status: Mapped[str] = mapped_column(String(16), default="启用")
    # 创建人 / 最后修改人：0 表示系统导入
    created_by: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int] = mapped_column(Integer, default=0)
    # 创建与更新时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

# 溯源表：为每条已入库采收记录生成公开溯源码
class Trace(Base):
    # 表名：nx_traces
    __tablename__ = "nx_traces"
    # 主键：自增溯源 ID
    id: Mapped[int] = mapped_column(primary_key=True)
    # 随机溯源码：URL 中的 48 位十六进制字符串，唯一
    token: Mapped[str] = mapped_column(String(64), unique=True)
    # 所属组织
    org: Mapped[str] = mapped_column(String(64), index=True)
    # 所属乡镇
    district: Mapped[str] = mapped_column(String(64))
    # 对应采收记录 ID：一条采收只能生成一次溯源，故加唯一约束
    harvest_id: Mapped[int] = mapped_column(ForeignKey("nx_records.id"), unique=True)
    # 对应库存批次 ID
    stock_id: Mapped[int] = mapped_column(ForeignKey("nx_stocks.id"))
    # 是否公开：默认 False，用户确认后才允许扫码查看
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # 公开快照：生成时冻结生产摘要，后续台账修改不影响已公开内容
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # 生成时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

# FastAPI 数据库依赖：每个 HTTP 请求获取一个独立会话
def get_db():
    # with 语句保证请求结束或异常时自动关闭会话、归还连接
    with SessionLocal() as db:
        # 把会话交给路由函数；路由结束后回到这里执行清理
        yield db
