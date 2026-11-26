"""使用隔离测试库验证知识库导入、BM25 检索、权限与 AI 引用。"""
from test_business import client, login
from app import main
from app.core import settings


def test_corpus_seeded_and_search(client):
    """三种角色都能浏览档案，常见问法能命中土壤质地条目。"""
    c = client
    for username in ("farmer", "regulator", "admin"):
        h = login(c, username)
        r = c.get("/api/knowledge/docs?size=200", headers=h)
        assert r.status_code == 200
        assert r.json()["total"] >= 96
    h = login(c)
    r = c.post("/api/knowledge/search", headers=h, json={"q": "土壤质地"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and items[0]["doc_id"] == "A1-01"
    assert items[0]["snippet"]


def test_crop_filter(client):
    """作物筛选只返回通用或目标作物的条目。"""
    h = login(client)
    r = client.post("/api/knowledge/search", headers=h, json={"q": "叶片发黄 病害", "crop": "番茄"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    for item in items:
        crops = " ".join(item["crop"])
        assert "通用" in crops or "番茄" in crops


def test_admin_only_management(client):
    """普通角色不能维护知识库，管理员增删后检索结果立即变化。"""
    c = client
    farmer, regulator, admin = login(c), login(c, "regulator"), login(c, "admin")
    payload = {
        "title": "测试知识条目",
        "domain_l1": "A",
        "domain_l2": "测试分类",
        "crop": ["通用"],
        "region": ["全国"],
        "keywords": ["知识库测试词"],
        "queries": ["知识库测试怎么查"],
        "content": "这是测试知识条目正文，用于验证检索与权限控制。",
        "source": "测试来源",
        "stability": "稳定",
        "authority": "B",
        "confidence": "高",
        "risk_level": "低",
        "version": "v1.0",
        "status": "启用",
    }
    for h in (farmer, regulator):
        assert c.post("/api/knowledge/docs", headers=h, json=payload).status_code == 403
    r = c.post("/api/knowledge/docs", headers=admin, json=payload)
    assert r.status_code == 200
    doc = r.json()
    doc_pk = doc["id"]
    assert doc["doc_id"].startswith("KB-")
    hits = c.post("/api/knowledge/search", headers=farmer, json={"q": "知识库测试词"}).json()["items"]
    assert any(item["id"] == doc_pk for item in hits)
    payload["title"] = "测试知识条目已更新"
    assert c.put(f"/api/knowledge/docs/{doc_pk}", headers=admin, json=payload).status_code == 200
    assert c.delete(f"/api/knowledge/docs/{doc_pk}", headers=farmer).status_code == 403
    assert c.delete(f"/api/knowledge/docs/{doc_pk}", headers=admin).status_code == 200
    hits = c.post("/api/knowledge/search", headers=farmer, json={"q": "知识库测试词"}).json()["items"]
    assert all(item["id"] != doc_pk for item in hits)


def test_seed_idempotent(client):
    """重复导入语料不会产生重复条目。"""
    c = client
    admin = login(c, "admin")
    before = c.get("/api/knowledge/docs?size=200", headers=admin).json()["total"]
    assert c.post("/api/knowledge/seed", headers=admin, json={}).status_code == 200
    after = c.get("/api/knowledge/docs?size=200", headers=admin).json()["total"]
    assert before == after


def test_ai_analyze_citations(client, monkeypatch):
    """AI 分析会把检索片段写入状态，并在结果中返回 citations。"""
    h = login(client)
    captured = []
    monkeypatch.setattr(settings, "qwen_api_key", "test-placeholder")

    async def model(state):
        captured.append(state)
        return {"answer": "可参考 [1] 进行土壤质地手测。", "review": "仅供参考", "steps": ["读取授权数据", "知识库检索"]}

    monkeypatch.setattr(main.workflow, "ainvoke", model)
    r = client.post("/api/ai/analyze", headers=h, json={"kind": "chat", "question": "土壤质地怎么判断"})
    assert r.status_code == 200
    job = r.json()
    assert job["result"]["citations"] and job["result"]["citations"][0]["doc_id"] == "A1-01"
    assert captured[0]["knowledge"][0]["doc_id"] == "A1-01"
    assert all(isinstance(item, int) for item in job["result"]["sources"])
