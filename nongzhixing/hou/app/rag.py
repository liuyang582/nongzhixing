# =============================================================================
# rag.py —— 内部 RAG 知识库
# 职责：导入农业知识语料，提供本地 BM25 检索、知识档案浏览与管理接口。
# 设计：不依赖外部向量库或新增依赖；检索片段只作为 AI 回答的依据，
#       不直接生成药剂处方，知识不足时必须由回答明确说明。
# =============================================================================

# 模块说明：全局共享知识档案；所有登录角色可检索，仅管理员可维护
"""农产品农技知识库：本地 BM25 检索、档案浏览与管理员维护。"""

# 导入 CSV 模块：导出知识档案
import csv
# 导入内存流：CSV 在内存中生成，不落临时文件
import io
# 导入 JSON：读取语料与序列化列表字段
import json
# 导入日志：语料缺失或损坏时记录原因，不阻断服务启动
import logging
# 导入数学函数：计算 BM25 的 IDF
import math
# 导入路径工具：解析随项目打包的语料文件
from pathlib import Path
# 导入正则：中文分词、Markdown 清理与元数据匹配
import re
# 导入安全随机数：管理员新增条目生成 KB- 编号
import secrets
# 导入线程锁：保护进程内索引缓存
import threading
# 导入 Unicode 规范化：统一全角/半角字符，提升检索命中
import unicodedata
# 导入计数器：统计词频与文档频率
from collections import Counter
# 导入类型：声明列表与迭代类型
from typing import Literal
# 导入 FastAPI 依赖、异常、查询参数与响应类型
from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
# 导入 Pydantic 基类、字段约束与校验器
from pydantic import BaseModel, Field, field_validator
# 导入 SQLAlchemy 查询函数
from sqlalchemy import func, select
# 导入知识库模型与全局配置
from .core import KnowledgeDoc, settings

# 日志器：记录语料导入与索引构建异常
logger = logging.getLogger("nongzhixing.rag")

# 语料默认路径：随项目打包，避免部署时依赖桌面目录
CORPUS_FILE = Path(__file__).resolve().parent / "data" / "agri_knowledge_v1.jsonl"
# 一级分类名称：与语料库设计规范 A–G 对应
DOMAIN_NAMES = {
    "A": "基础农艺",
    "B": "作物栽培",
    "C": "植物保护",
    "D": "设施农业与智慧农业",
    "E": "区域特色农业",
    "F": "政策法规与标准",
    "G": "质量安全与追溯",
}
# 通用标记：作物写“通用”、地区写“全国”时对任何筛选都命中
CROP_UNIVERSAL = {"通用", "通用作物", "主要农作物", "各种作物", "蔬菜通用"}
REGION_UNIVERSAL = {"全国", "通用"}
# 常见停用词：中文单字与二元组中过滤，减少噪声命中
STOPWORDS = {"的", "了", "和", "与", "及", "或", "在", "是", "有", "为", "对", "怎么", "如何", "什么", "怎样", "可以", "需要", "应该", "请问", "一下"}
# 字段权重：标题、关键词、问法的命中比正文更有价值
FIELD_WEIGHTS = (("title", 3.0), ("keywords", 3.0), ("queries", 2.5), ("domain_l2", 1.5), ("content", 1.0))
# BM25 参数
K1, B = 1.2, 0.75
# ASCII 词与数字编号：保留 pH、EC、NY/T、GB 2763 等
ASCII_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
# 连续中文字符
CJK_RE = re.compile(r"[一-鿿]+")


# 文本规范化：全角转半角、统一小写，保证查询与索引使用同一口径
def normalize(text):
    # NFKC 归一化后转小写
    return unicodedata.normalize("NFKC", str(text or "")).lower()


# 中文分词：ASCII 词 + 中文单字 + 重叠二元组，无需 jieba 等额外依赖
def tokenize(text):
    # 先做规范化
    value = normalize(text)
    # 结果列表
    tokens = []
    # ASCII 单词与编号
    for word in ASCII_RE.findall(value):
        # 过滤单字符和停用词
        if word not in STOPWORDS and len(word) > 1:
            tokens.append(word)
    # 连续中文片段
    for run in CJK_RE.findall(value):
        # 单字：提高短查询的召回
        tokens.extend(ch for ch in run if ch not in STOPWORDS)
        # 二元组：保留“土壤”“壤质”“质地”等组合语义
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1) if run[i:i + 2] not in STOPWORDS)
    # 返回词元
    return tokens


# 列表展开：把“小麦/油菜/蔬菜”拆成可比较的独立名称
def _expand(values):
    # 结果集合
    out = set()
    # 逐项拆分斜杠、顿号、逗号与空白
    for value in values or []:
        text = str(value).strip()
        if not text:
            continue
        out.add(text)
        for part in re.split(r"[/、,，;；\s]+", text):
            if part:
                out.add(part)
    return out


# 元数据匹配：筛选项与文档列表存在包含关系时视为命中
def _match_meta(values, query, universal):
    # 未填写筛选条件时全部通过
    if not query:
        return True
    # 通用/全国条目始终通过
    if _expand(values) & universal:
        return True
    # 查询词与任一名词互相包含即命中
    return any(query == item or query in item or item in query for item in _expand(values))


# 文档瘦身：从 ORM 对象提取索引所需字段，避免会话关闭后访问失效
def _doc_payload(doc):
    return {
        "id": doc.id,
        "doc_id": doc.doc_id,
        "title": doc.title,
        "domain_l1": doc.domain_l1,
        "domain_l2": doc.domain_l2,
        "crop": list(doc.crop or []),
        "region": list(doc.region or []),
        "stage": list(doc.stage or []),
        "operation": list(doc.operation or []),
        "keywords": list(doc.keywords or []),
        "queries": list(doc.queries or []),
        "content": doc.content or "",
        "source": doc.source or "",
        "stability": doc.stability or "",
        "authority": doc.authority or "",
        "confidence": doc.confidence or "",
        "risk_level": doc.risk_level or "",
        "version": doc.version or "",
        "corpus": bool(doc.corpus),
        "status": doc.status or "启用",
    }


# 序列化摘要：列表字段直接返回数组，前端按标签展示
def _summary(payload):
    return {
        "id": payload["id"],
        "doc_id": payload["doc_id"],
        "title": payload["title"],
        "domain_l1": payload["domain_l1"],
        "domain_l2": payload["domain_l2"],
        "crop": payload["crop"],
        "region": payload["region"],
        "stage": payload["stage"],
        "operation": payload["operation"],
        "keywords": payload["keywords"],
        "queries": payload["queries"],
        "source": payload["source"],
        "stability": payload["stability"],
        "authority": payload["authority"],
        "confidence": payload["confidence"],
        "risk_level": payload["risk_level"],
        "version": payload["version"],
        "corpus": payload["corpus"],
        "status": payload["status"],
    }


# 序列化详情：在摘要基础上追加完整正文
def _detail(payload):
    return {**_summary(payload), "content": payload["content"]}


# 片段提取：按空行分段，选择与查询重合度最高的一段，并清理 Markdown 标记
def snippet(payload, query, limit=180):
    # 原文
    text = payload["content"] or ""
    # 分段并清理标题/引用/加粗等 Markdown 符号
    paragraphs = [re.sub(r"[#>*`]+", "", part).strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    # 查询词元集合
    query_tokens = set(tokenize(query))
    # 最佳段落与得分
    best, best_score = "", -1.0
    # 逐段比较
    for part in paragraphs:
        # 词元重合数
        overlap = len(set(tokenize(part)) & query_tokens)
        # 整句命中额外加分
        bonus = 2.0 if normalize(query) and normalize(query) in normalize(part) else 0.0
        # 更新最佳段落
        if overlap + bonus > best_score:
            best, best_score = part, overlap + bonus
    # 没有正文时使用标题兜底
    value = re.sub(r"\s+", " ", best or payload["title"]).strip()
    # 截断并追加省略号
    return value[:limit] + ("…" if len(value) > limit else "")


# 进程内索引：文档词频、长度、文档频率与平均长度
class _Index:
    # 使用固定属性，减少内存开销
    __slots__ = ("docs", "counts", "lengths", "avg", "df", "n")

    def __init__(self, docs):
        # 文档载荷列表
        self.docs = docs
        # 每篇文档的加权词频
        self.counts = []
        # 每篇文档的加权长度
        self.lengths = []
        # 文档频率
        df = Counter()
        # 逐篇统计
        for payload in docs:
            counts = Counter()
            # 按字段权重累加词频
            for attr, weight in FIELD_WEIGHTS:
                value = payload.get(attr, "")
                text = " ".join(map(str, value)) if isinstance(value, list) else str(value)
                for token in tokenize(text):
                    counts[token] += weight
            self.counts.append(counts)
            # 文档长度按加权词频求和
            self.lengths.append(sum(counts.values()) or 1.0)
            # 记录出现过的词元
            df.update(counts.keys())
        # 保存文档频率
        self.df = df
        # 文档总数
        self.n = max(len(docs), 1)
        # 平均文档长度
        self.avg = sum(self.lengths) / self.n or 1.0


# 索引缓存：版本号变化时重建
_index_lock = threading.Lock()
_index_cache = {"version": None, "index": None}


# 索引失效：知识条目增删改后调用，下一次检索时重建
def invalidate():
    # 加锁修改缓存版本
    with _index_lock:
        _index_cache["version"] = None
        _index_cache["index"] = None


# 数据库版本：文档数量 + 最后更新时间，用于判断索引是否过期
def _db_version(db):
    # 统计启用条目数量与最后更新时间
    count, latest = db.execute(select(func.count(KnowledgeDoc.id), func.max(KnowledgeDoc.updated_at)).where(KnowledgeDoc.status == "启用")).one()
    # 返回可比较的版本元组
    return (int(count or 0), str(latest or ""))


# 获取索引：命中缓存直接返回，否则读取数据库重建
def get_index(db):
    # 先计算版本
    version = _db_version(db)
    # 读取缓存
    with _index_lock:
        if _index_cache["version"] == version and _index_cache["index"] is not None:
            return _index_cache["index"]
    # 加载全部启用条目并构建载荷
    docs = [_doc_payload(doc) for doc in db.scalars(select(KnowledgeDoc).where(KnowledgeDoc.status == "启用")).all()]
    # 构建索引
    index = _Index(docs)
    # 写回缓存
    with _index_lock:
        _index_cache["version"] = version
        _index_cache["index"] = index
    # 返回索引
    return index


# 检索：BM25 打分 + 元数据过滤 + 整句短语加分
def search(db, query, crop="", region="", domain_l1="", limit=8):
    # 查询词元计数
    query_tokens = Counter(tokenize(query))
    # 没有有效词元时返回空结果
    if not query_tokens:
        return []
    # 获取索引
    index = get_index(db)
    # 规范化查询，用于短语加分
    normalized = normalize(query).strip()
    # 候选结果
    scored = []
    # 逐篇打分
    for payload, counts, length in zip(index.docs, index.counts, index.lengths):
        # 分类过滤
        if domain_l1 and payload["domain_l1"] != domain_l1:
            continue
        # 作物过滤
        if crop and not _match_meta(payload["crop"], crop, CROP_UNIVERSAL):
            continue
        # 地区过滤
        if region and not _match_meta(payload["region"], region, REGION_UNIVERSAL):
            continue
        # BM25 分数
        score = 0.0
        for token, qtf in query_tokens.items():
            # 文档中的加权词频
            tf = counts.get(token, 0.0)
            if not tf:
                continue
            # 文档频率与 IDF
            df = index.df.get(token, 0)
            idf = math.log(1 + (index.n - df + 0.5) / (df + 0.5))
            # BM25 词频饱和
            denominator = tf + K1 * (1 - B + B * length / index.avg)
            score += idf * tf * (K1 + 1) / denominator * (1 + math.log(qtf)) if qtf > 1 else idf * tf * (K1 + 1) / denominator
        # 查询整句出现在标题或关键词中时加分
        if normalized:
            if normalized in normalize(payload["title"]):
                score += 4.0
            elif any(normalized in normalize(keyword) for keyword in payload["keywords"]):
                score += 3.0
        # 无有效命中则跳过
        if score <= 0:
            continue
        # 记录分数
        scored.append((score, payload))
    # 按分数倒序，距离近的在前
    scored.sort(key=lambda item: item[0], reverse=True)
    # 组装检索结果
    hits = []
    for score, payload in scored[:max(1, min(int(limit), 20))]:
        hits.append({**_summary(payload), "score": round(score, 3), "snippet": snippet(payload, query)})
    # 返回结果
    return hits


# 语料路径：优先使用环境变量配置，否则使用随项目打包的副本
def corpus_path():
    # 配置路径存在时使用配置
    if settings.rag_corpus_path:
        return Path(settings.rag_corpus_path)
    # 默认打包路径
    return CORPUS_FILE


# 导入语料：按 doc_id 只插入缺失条目，不覆盖管理员已修改内容
def seed_corpus(db):
    # 目标文件
    path = corpus_path()
    # 文件不存在时记录日志并返回，不阻断启动
    if not path.exists():
        logger.warning("知识库语料不存在：%s", path)
        return {"inserted": 0, "skipped": 0, "path": str(path), "reason": "语料文件不存在"}
    # 已存在的编号，避免逐条查询
    existing = set(db.scalars(select(KnowledgeDoc.doc_id)).all())
    # 插入计数
    inserted = 0
    # 跳过计数
    skipped = 0
    # 逐行读取 JSONL
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                # 跳过空行
                if not line.strip():
                    continue
                # 单行损坏时跳过，不影响其余条目
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("知识库语料存在无法解析的行：%s", path)
                    continue
                # 语料编号
                doc_id = str(row.get("doc_id", "")).strip()[:32]
                # 缺少编号或已存在时跳过
                if not doc_id or doc_id in existing:
                    skipped += 1
                    continue
                # 写入知识档案
                db.add(KnowledgeDoc(
                    doc_id=doc_id,
                    title=str(row.get("title", ""))[:200],
                    domain_l1=str(row.get("domain_l1", ""))[:8],
                    domain_l2=str(row.get("domain_l2", ""))[:64],
                    crop=[str(x)[:64] for x in row.get("crop", []) if str(x).strip()],
                    region=[str(x)[:64] for x in row.get("region", []) if str(x).strip()],
                    stage=[str(x)[:64] for x in row.get("stage", []) if str(x).strip()],
                    operation=[str(x)[:64] for x in row.get("operation", []) if str(x).strip()],
                    keywords=[str(x)[:64] for x in row.get("keywords", []) if str(x).strip()],
                    queries=[str(x)[:64] for x in row.get("queries", []) if str(x).strip()],
                    content=str(row.get("content", "")),
                    source=str(row.get("source", ""))[:500],
                    stability=str(row.get("stability", "稳定"))[:16],
                    authority=str(row.get("authority", "B"))[:4],
                    confidence=str(row.get("confidence", ""))[:16],
                    risk_level=str(row.get("risk_level", "低"))[:8],
                    version=str(row.get("version", "v1.0"))[:16],
                    corpus=True,
                    status="启用",
                    created_by=0,
                    updated_by=0,
                ))
                # 记录已插入编号
                existing.add(doc_id)
                inserted += 1
    # 数据库写入失败时回滚，避免半批数据
    except Exception:
        db.rollback()
        logger.exception("知识库语料导入失败：%s", path)
        return {"inserted": 0, "skipped": skipped, "path": str(path), "reason": "导入失败"}
    # 有新增时提交
    if inserted:
        db.commit()
    # 索引失效，下一次检索时重建
    invalidate()
    # 返回统计
    return {"inserted": inserted, "skipped": skipped, "path": str(path)}


# 检索请求体
class SearchBody(BaseModel):
    # 查询词：2–200 字
    q: str = Field(min_length=2, max_length=200)
    # 作物筛选：为空不过滤
    crop: str = Field(default="", max_length=64)
    # 地区筛选：为空不过滤
    region: str = Field(default="", max_length=64)
    # 一级分类筛选：A–G 或空
    domain_l1: str = Field(default="", max_length=1)
    # 返回条数
    limit: int = Field(default=8, ge=1, le=20)

    # 分类只接受 A–G
    @field_validator("domain_l1")
    @classmethod
    def check_domain(cls, value):
        # 统一大写并去除空白
        value = (value or "").strip().upper()
        # 非法分类拒绝
        if value and value not in DOMAIN_NAMES:
            raise ValueError("分类无效")
        # 返回规范化值
        return value


# 知识档案新增/修改请求体
class KnowledgeInput(BaseModel):
    # 标题
    title: str = Field(min_length=1, max_length=200)
    # 一级分类
    domain_l1: str = Field(default="", max_length=1)
    # 二级分类
    domain_l2: str = Field(default="", max_length=64)
    # 适用作物、地区、生育期、环节
    crop: list[str] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    stage: list[str] = Field(default_factory=list)
    operation: list[str] = Field(default_factory=list)
    # 检索关键词与常见问法
    keywords: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    # 正文与来源
    content: str = Field(min_length=1, max_length=8000)
    source: str = Field(min_length=1, max_length=500)
    # 时效、权威、置信、风险、版本与状态
    stability: Literal["稳定", "年度更新", "时效性"] = "稳定"
    authority: Literal["A", "B", "C"] = "B"
    confidence: str = Field(default="", max_length=16)
    risk_level: Literal["高", "中", "低"] = "低"
    version: str = Field(default="v1.0", max_length=16)
    status: Literal["启用", "停用"] = "启用"

    # 分类只接受 A–G
    @field_validator("domain_l1")
    @classmethod
    def check_domain(cls, value):
        # 统一大写并去除空白
        value = (value or "").strip().upper()
        # 非法分类拒绝
        if value and value not in DOMAIN_NAMES:
            raise ValueError("分类无效")
        # 返回规范化值
        return value

    # 列表字段统一去重、去空白并限制单项长度
    @field_validator("crop", "region", "stage", "operation", "keywords", "queries")
    @classmethod
    def clean_list(cls, value):
        # 去重结果
        out = []
        # 逐项清理
        for item in value or []:
            text = str(item).strip()
            if text and text not in out:
                out.append(text[:64])
        # 最多 20 项，避免超大请求
        if len(out) > 20:
            raise ValueError("列表最多 20 项")
        # 返回清理后的列表
        return out


# 管理员校验：知识库全局共享，只有系统管理员可写入
def admin_only(user):
    # 非管理员拒绝
    if user.role != "admin":
        raise HTTPException(403, "仅系统管理员可维护知识库")


# CSV 单元格转义：防止以公式字符开头的内容在 Excel 中被执行
def _safe_cell(value):
    # 列表用顿号连接
    text = "、".join(map(str, value)) if isinstance(value, list) else str(value or "")
    # 以公式字符开头时加单引号
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


# 安装函数：main.py 启动时调用，把知识库接口注册到 FastAPI 实例
def install(app, ns):
    # 复用主模块的鉴权、数据库会话与审计函数
    current_user = ns["current_user"]
    get_db = ns["get_db"]
    audit = ns["audit"]

    # 档案浏览：支持关键词、作物、地区、分类与分页
    @app.get("/api/knowledge/docs")
    def list_docs(q: str = Query("", max_length=64), crop: str = Query("", max_length=64), region: str = Query("", max_length=64), domain_l1: str = Query("", max_length=1), page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), user=Depends(current_user), db=Depends(get_db)):
        # 按分类和编号排序，保证浏览顺序稳定
        rows = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.domain_l1, KnowledgeDoc.doc_id)).all()
        # 载荷列表
        docs = [_doc_payload(row) for row in rows]
        # 统一分类大写
        domain_l1 = (domain_l1 or "").strip().upper()
        # 关键词清理
        q = q.strip()
        # 逐条过滤
        filtered = []
        for doc in docs:
            # 分类过滤
            if domain_l1 and doc["domain_l1"] != domain_l1:
                continue
            # 作物过滤
            if crop and not _match_meta(doc["crop"], crop, CROP_UNIVERSAL):
                continue
            # 地区过滤
            if region and not _match_meta(doc["region"], region, REGION_UNIVERSAL):
                continue
            # 关键词搜索：标题、编号、二级分类、关键词
            if q:
                haystack = " ".join([doc["title"], doc["doc_id"], doc["domain_l2"], " ".join(doc["keywords"])])
                if q not in haystack:
                    continue
            # 加入结果
            filtered.append(_summary(doc))
        # 分页切片
        start = (page - 1) * size
        # 返回分页数据、总数与分类名称
        return {"items": filtered[start:start + size], "total": len(filtered), "page": page, "size": size, "domains": DOMAIN_NAMES}

    # 单条详情：返回完整正文
    @app.get("/api/knowledge/docs/{doc_pk}")
    def get_doc(doc_pk: int, user=Depends(current_user), db=Depends(get_db)):
        # 按主键查询
        doc = db.get(KnowledgeDoc, doc_pk)
        # 不存在返回 404
        if not doc:
            raise HTTPException(404, "知识条目不存在")
        # 返回详情
        return _detail(_doc_payload(doc))

    # 检索：返回 BM25 命中片段与来源
    @app.post("/api/knowledge/search")
    def search_docs(body: SearchBody, user=Depends(current_user), db=Depends(get_db)):
        # 执行检索
        hits = search(db, body.q, body.crop, body.region, body.domain_l1, body.limit)
        # 返回结果与提示
        return {"query": body.q, "items": hits, "count": len(hits), "note": "字面检索结果只作参考依据，不构成用药处方；时效性资料需核对最新公告。"}

    # CSV 导出：所有登录角色可用，操作留审计
    @app.get("/api/knowledge/export/csv")
    def export_csv(q: str = Query("", max_length=64), crop: str = Query("", max_length=64), region: str = Query("", max_length=64), domain_l1: str = Query("", max_length=1), user=Depends(current_user), db=Depends(get_db)):
        # 读取全部档案
        rows = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.domain_l1, KnowledgeDoc.doc_id)).all()
        # 载荷列表
        docs = [_doc_payload(row) for row in rows]
        # 统一分类
        domain_l1 = (domain_l1 or "").strip().upper()
        # 关键词
        q = q.strip()
        # 逐条过滤
        for_export = []
        for doc in docs:
            if domain_l1 and doc["domain_l1"] != domain_l1:
                continue
            if crop and not _match_meta(doc["crop"], crop, CROP_UNIVERSAL):
                continue
            if region and not _match_meta(doc["region"], region, REGION_UNIVERSAL):
                continue
            if q:
                haystack = " ".join([doc["title"], doc["doc_id"], doc["domain_l2"], " ".join(doc["keywords"])])
                if q not in haystack:
                    continue
            for_export.append(doc)
        # 内存 CSV
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        # 表头
        writer.writerow(["编号", "标题", "一级分类", "二级分类", "作物", "地区", "生育期", "环节", "关键词", "常见问法", "来源", "时效", "权威", "置信", "风险", "版本", "正文"])
        # 数据行
        for doc in for_export:
            writer.writerow([_safe_cell(doc[key]) for key in ("doc_id", "title", "domain_l1", "domain_l2", "crop", "region", "stage", "operation", "keywords", "queries", "source", "stability", "authority", "confidence", "risk_level", "version", "content")])
        # 写入审计
        audit(db, user, "导出知识库档案", {"count": len(for_export)}); db.commit()
        # 加 BOM 方便 Excel 识别 UTF-8
        data = ("﻿" + buffer.getvalue()).encode("utf-8")
        # 返回附件
        return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="knowledge.csv"'})

    # 新增条目：仅管理员
    @app.post("/api/knowledge/docs")
    def create_doc(body: KnowledgeInput, user=Depends(current_user), db=Depends(get_db)):
        # 管理员校验
        admin_only(user)
        # 自动生成知识库编号
        doc_id = "KB-" + secrets.token_hex(4)
        # 创建档案
        doc = KnowledgeDoc(doc_id=doc_id, corpus=False, created_by=user.id, updated_by=user.id, **body.model_dump())
        # 写库
        db.add(doc); db.flush()
        # 审计
        audit(db, user, "新增知识条目", {"id": doc.id, "doc_id": doc_id}); db.commit()
        # 索引失效
        invalidate()
        # 返回详情
        return _detail(_doc_payload(doc))

    # 修改条目：仅管理员
    @app.put("/api/knowledge/docs/{doc_pk}")
    def update_doc(doc_pk: int, body: KnowledgeInput, user=Depends(current_user), db=Depends(get_db)):
        # 管理员校验
        admin_only(user)
        # 查询条目
        doc = db.get(KnowledgeDoc, doc_pk)
        # 不存在返回 404
        if not doc:
            raise HTTPException(404, "知识条目不存在")
        # 修改前快照
        before = _summary(_doc_payload(doc))
        # 写入新字段
        for key, value in body.model_dump().items():
            setattr(doc, key, value)
        # 记录修改人
        doc.updated_by = user.id
        # 审计
        audit(db, user, "修改知识条目", {"id": doc.id, "doc_id": doc.doc_id, "before": before}); db.commit()
        # 索引失效
        invalidate()
        # 返回详情
        return _detail(_doc_payload(doc))

    # 删除条目：仅管理员
    @app.delete("/api/knowledge/docs/{doc_pk}")
    def delete_doc(doc_pk: int, user=Depends(current_user), db=Depends(get_db)):
        # 管理员校验
        admin_only(user)
        # 查询条目
        doc = db.get(KnowledgeDoc, doc_pk)
        # 不存在返回 404
        if not doc:
            raise HTTPException(404, "知识条目不存在")
        # 删除前快照
        snapshot = _summary(_doc_payload(doc))
        # 记录审计后删除
        audit(db, user, "删除知识条目", {"snapshot": snapshot}); db.delete(doc); db.commit()
        # 索引失效
        invalidate()
        # 返回成功
        return {"ok": True}

    # 手动补导语料：仅管理员，幂等
    @app.post("/api/knowledge/seed")
    def reseed(user=Depends(current_user), db=Depends(get_db)):
        # 管理员校验
        admin_only(user)
        # 执行导入
        result = seed_corpus(db)
        # 审计
        audit(db, user, "导入知识语料库", result); db.commit()
        # 返回统计
        return result
