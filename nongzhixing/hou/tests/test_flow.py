import base64
from fastapi import HTTPException
from test_business import client, login, another_farmer
from app import main
from app.core import settings

PHOTO='data:image/png;base64,'+'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR3sAAAAASUVORK5CYII='

def prepare(c,h,name='流程地块'):
    land=c.post('/api/records/lands',headers=h,json={'title':name,'data':{'crop':'番茄','latitude':30.27,'longitude':120.15}}).json()
    growth=c.post('/api/records/growth',headers=h,json={'title':name+'批次','data':{'plot_id':land['id'],'plot':name,'crop':'番茄','sow_date':'2026-08-01','stage':'开花结果期','note':'观察下部叶片'}}).json()
    assert 'id' in growth
    env=c.post('/api/records/environment',headers=h,json={'title':name+'测量','data':{'plot_id':land['id'],'plot':name,'temperature':26,'humidity':68,'soil':45,'source':'人工记录'}})
    assert env.status_code==200
    return land,growth,env.json()

def enable(monkeypatch,captured,fail_weather=False):
    monkeypatch.setattr(settings,'qwen_api_key','test-placeholder')
    async def weather(**kwargs):
        if fail_weather: raise HTTPException(502,'测试天气服务不可用')
        return {'source':'测试天气','latitude':kwargs['latitude'],'longitude':kwargs['longitude'],'current':{'temperature_2m':25},'cached':False}
    async def model(state):
        captured.append(state)
        return {'answer':'测试模型：先现场巡检并记录叶片范围。','review':'待人工确认','steps':['读取地块','查看照片','等待人工确认']}
    monkeypatch.setattr(main,'weather',weather)
    monkeypatch.setattr(main.workflow,'ainvoke',model)

def analyze(c,h,land,growth):
    return c.post('/api/ai/analyze',headers=h,json={'kind':'diagnosis','question':'叶片发黄如何检查？','plot_id':land['id'],'growth_id':growth['id'],'image':PHOTO})

def test_complete_plot_flow(client,monkeypatch):
    h=login(client);land,growth,env=prepare(client,h);captured=[];enable(monkeypatch,captured)
    r=analyze(client,h,land,growth);assert r.status_code==200
    job=r.json();assert job['status']=='待确认' and job['result']['photo_id']
    assert {r['id'] for r in job['result']['records']}=={growth['id'],env['id']}
    assert captured[0]['crop']=='番茄' and captured[0]['image']==PHOTO
    assert job['result']['weather']['latitude']==30.27
    other=another_farmer(client)
    assert client.get(f"/api/plots/{land['id']}/flow",headers=other).status_code==404
    assert client.get(f"/api/files/{job['result']['photo_id']}",headers=other).status_code==404
    assert client.post(f"/api/ai/jobs/{job['id']}/confirm",headers=other,json={}).status_code==404
    confirmed=client.post(f"/api/ai/jobs/{job['id']}/confirm",headers=h,json={'title':'叶片现场巡检','assignee':'张师傅','date':'2026-10-02','note':'检查叶背和根区'});assert confirmed.status_code==200
    assert client.post(f"/api/ai/jobs/{job['id']}/confirm",headers=h,json={}).status_code==409
    flow=client.get(f"/api/plots/{land['id']}/flow",headers=h).json();task=flow['tasks'][0]
    assert task['data']['ai_job_id']==job['id'] and task['data']['growth_id']==growth['id'] and task['data']['assignee']=='张师傅'
    body={'title':task['title'],'status':'已完成','version':task['version'],'data':{**task['data'],'note':''}}
    assert client.put(f"/api/records/tasks/{task['id']}",headers=h,json=body).status_code==422
    body['data']['note']='检查后未发现虫体，清理排水沟，三天后复查。'
    assert client.put(f"/api/records/tasks/{task['id']}",headers=h,json=body).status_code==200
    assert client.put(f"/api/records/tasks/{task['id']}",headers=h,json=body).status_code==409
    assert client.get(f"/api/plots/{land['id']}/flow",headers=h).json()['tasks'][0]['status']=='已完成'
    assert client.delete(f"/api/records/lands/{land['id']}",headers=h).status_code==409
    assert client.delete(f"/api/records/growth/{growth['id']}",headers=h).status_code==409

def test_plot_mismatch_and_rejection(client,monkeypatch):
    h=login(client);a,g,_=prepare(client,h,'地块甲');b,bg,_=prepare(client,h,'地块乙');captured=[];enable(monkeypatch,captured)
    assert analyze(client,h,a,bg).status_code==422
    r=analyze(client,h,a,g).json()
    assert all(x['data']['plot_id']==a['id'] for x in r['result']['records'])
    assert client.post(f"/api/ai/jobs/{r['id']}/reject",headers=h,json={}).status_code==200
    assert client.post(f"/api/ai/jobs/{r['id']}/confirm",headers=h,json={}).status_code==409
    assert client.get(f"/api/plots/{a['id']}/flow",headers=h).json()['tasks']==[]
    assert client.post('/api/records/tasks',headers=h,json={'title':'伪造','data':{'type':'巡检','ai_job_id':r['id']}}).status_code==422

def test_weather_failure_preserved_and_invalid_image(client,monkeypatch):
    h=login(client);land,g,_=prepare(client,h);captured=[];enable(monkeypatch,captured,True)
    r=analyze(client,h,land,g);assert r.status_code==200
    assert r.json()['result']['weather']['unavailable'] is True
    assert client.post('/api/ai/analyze',headers=h,json={'kind':'diagnosis','question':'检查叶片','plot_id':land['id'],'growth_id':g['id'],'image':'data:image/png;base64,aGVsbG8='}).status_code==422
