"""使用隔离测试库验证权限、库存事务和人工确认，不接触用户 MySQL。"""
import os
from pathlib import Path
import tempfile
import pytest

test_root = Path(tempfile.mkdtemp(prefix="nx-test-"))
os.environ["DATABASE_URL"] = "sqlite:///" + str(test_root / "test.db")
os.environ["QWEN_API_KEY"] = ""
os.environ["JWT_SECRET"] = "unit-test-secret-not-for-production-1234567890"
from fastapi.testclient import TestClient
from app import main
from app.core import Base, engine, settings

class FakeRedis:
    def __init__(self): self.values = {}
    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]
    async def expire(self, key, seconds): return True
    async def get(self, key): return self.values.get(key)
    async def ping(self): return True
    async def aclose(self): pass
    async def set(self, key, value, **kwargs): self.values[key] = value; return True
    async def xadd(self, *args, **kwargs): return "1-0"

@pytest.fixture
def client(monkeypatch):
    assert engine.dialect.name == "sqlite"
    Base.metadata.drop_all(engine)
    monkeypatch.setattr(main, "cache", FakeRedis())
    with TestClient(main.app) as c:
        yield c

def login(c, username="farmer", password="demo123"):
    r = c.post("/api/auth/login", json={"username":username,"password":password})
    assert r.status_code == 200
    return {"Authorization":"Bearer " + r.json()["token"]}

def another_farmer(c):
    admin=login(c,"admin")
    r=c.post("/api/admin/users",headers=admin,json={"username":"other","name":"其他农场","password":"testpass123","role":"farmer","org":"另一个农场","district":"其他乡镇"})
    assert r.status_code==200
    return login(c,"other","testpass123")

def test_auth_and_row_isolation(client):
    c=client
    assert c.get("/api/dashboard").status_code==401
    assert c.post("/api/auth/login",json={"username":"farmer","password":"wrong"}).status_code==401
    farmer=login(c); other=another_farmer(c)
    own=c.get("/api/records/growth",headers=farmer).json()
    assert own["total"]==1
    assert c.get("/api/records/growth",headers=other).json()["total"]==0
    row=own["items"][0]
    assert c.delete(f"/api/records/growth/{row['id']}",headers=other).status_code==404
    assert c.get("/api/admin/users",headers=farmer).status_code==403
    regulator=login(c,"regulator")
    assert c.get("/api/records/growth",headers=regulator).json()["total"]==1
    assert c.post("/api/records/growth",headers=regulator,json={"title":"越权","data":{}}).status_code==403

def test_validation_and_optimistic_update(client):
    h=login(client)
    assert client.post("/api/records/environment",headers=h,json={"title":"异常数值","data":{"plot":"01","temperature":25,"humidity":101,"soil":20,"source":"人工记录"}}).status_code==422
    r=client.post("/api/records/tasks",headers=h,json={"title":"测试巡查","data":{"type":"巡检","note":"真实测试"}})
    assert r.status_code==200
    row=r.json();body={"title":"更新巡查","data":row["data"],"version":row["version"]}
    assert client.put(f"/api/records/tasks/{row['id']}",headers=h,json=body).status_code==200
    assert client.put(f"/api/records/tasks/{row['id']}",headers=h,json=body).status_code==409

def test_stock_reservation_and_idempotency(client):
    h=login(client);stock=client.get('/api/stocks',headers=h).json()[0]
    order={"stock_id":stock['id'],"customer":"测试客户","quantity":150,"price":6}
    r=client.post('/api/orders',headers=h,json=order);assert r.status_code==200
    oid=r.json()['id']
    assert client.post('/api/orders',headers=h,json=order).status_code==409
    assert client.get('/api/stocks',headers=h).json()[0]['available']==50
    assert client.post(f'/api/orders/{oid}/ship',headers=h,json={}).status_code==200
    assert client.post(f'/api/orders/{oid}/ship',headers=h,json={}).status_code==409
    final=client.get('/api/stocks',headers=h).json()[0]
    assert final['quantity']==50 and final['reserved']==0
    order['quantity']=20
    oid2=client.post('/api/orders',headers=h,json=order).json()['id']
    assert client.post(f'/api/orders/{oid2}/cancel',headers=h,json={}).status_code==200
    assert client.get('/api/stocks',headers=h).json()[0]['available']==50

def test_file_isolation_and_safe_export(client):
    h=login(client);other=another_farmer(client)
    r=client.post('/api/files',headers=h,files={'file':('report.txt',b'evidence','text/plain')});assert r.status_code==200
    assert client.get('/api/files/'+str(r.json()['id']),headers=other).status_code==404
    assert client.get('/api/files/'+str(r.json()['id']),headers=h).content==b'evidence'
    client.post('/api/records/tasks',headers=h,json={'title':'=1+1','data':{'type':'巡检'}})
    export=client.get('/api/records/tasks/export/csv',headers=h)
    assert export.status_code==200 and "'=1+1" in export.content.decode('utf-8-sig')

def test_gis_geometry_validation(client):
    h=login(client)
    geo={'type':'Polygon','coordinates':[[[120,30],[120.001,30],[120.001,30.001],[120,30.001],[120,30]]]}
    r=client.post('/api/records/lands',headers=h,json={'title':'绘制地块','data':{'geometry':geo}})
    assert r.status_code==200 and r.json()['data']['measured_area']>0
    geo['coordinates'][0][0]=[999,999]
    assert client.post('/api/records/lands',headers=h,json={'title':'错误坐标','data':{'geometry':geo}}).status_code==422

def test_ai_confirmation_once(client,monkeypatch):
    h=login(client)
    assert client.post('/api/ai/analyze',headers=h,json={'question':'如何检查湿度？'}).status_code==503
    monkeypatch.setattr(settings,'qwen_api_key','unit-test-placeholder')
    async def fake(state):return {'answer':'请人工检查设备。','review':'待人工确认','steps':['资料检查','生成建议']}
    monkeypatch.setattr(main.workflow,'ainvoke',fake)
    r=client.post('/api/ai/analyze',headers=h,json={'question':'如何检查湿度？','kind':'farm','crop':'番茄'})
    assert r.status_code==200
    job=r.json()['id']
    assert client.post(f'/api/ai/jobs/{job}/confirm',headers=h,json={}).status_code==200
    assert client.post(f'/api/ai/jobs/{job}/confirm',headers=h,json={}).status_code==409
