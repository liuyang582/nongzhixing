"""最终验收的地图、附件和 AI 失败分支，全部使用隔离 SQLite。"""
import json
from test_business import client, login, another_farmer
from app import main


def test_gis_import_save_and_attachment_roundtrip(client):
    c = client
    h = login(c)
    geometry = {'type': 'Polygon', 'coordinates': [[[120.15, 30.27], [120.151, 30.27], [120.151, 30.271], [120.15, 30.271], [120.15, 30.27]]]}
    geo = {'type': 'Feature', 'geometry': geometry, 'properties': {}}
    imported = c.post('/api/gis/import', headers=h, files={'file': ('test.geojson', json.dumps(geo), 'application/geo+json')})
    assert imported.status_code == 200
    assert imported.json()[0]['area'] > 0
    saved = c.post('/api/records/lands', headers=h, json={'title': '隔离边界保存', 'data': {'geometry': geometry}})
    assert saved.status_code == 200
    rows = c.get('/api/records/lands?q=隔离边界保存', headers=h).json()['items']
    assert rows[0]['data']['geometry'] == geometry
    assert rows[0]['data']['measured_area'] > 0
    assert c.post('/api/gis/import', headers=h, files={'file': ('bad.geojson', b'bad', 'application/json')}).status_code == 422
    assert c.post('/api/gis/import', headers=login(c, 'regulator'), files={'file': ('test.geojson', json.dumps(geo), 'application/json')}).status_code == 403
    content = '最终附件验收：合成资料，无真实合同。'.encode()
    uploaded = c.post('/api/files', headers=h, files={'file': ('acceptance.txt', content, 'text/plain')})
    assert uploaded.status_code == 200
    fid = uploaded.json()['id']
    assert c.get(f'/api/files/{fid}', headers=h).content == content
    assert c.get(f'/api/files/{fid}', headers=another_farmer(c)).status_code == 404


def test_ai_failure_is_visible_and_does_not_create_task(client, monkeypatch):
    c = client
    h = login(c)
    monkeypatch.setattr(main.settings, 'qwen_api_key', 'isolated-failure-test')
    async def fail(state):
        raise TimeoutError('synthetic failure')
    monkeypatch.setattr(main.workflow, 'ainvoke', fail)
    before = c.get('/api/records/tasks', headers=h).json()['total']
    response = c.post('/api/ai/analyze', headers=h, json={'kind': 'chat', 'question': '最终隔离验收失败分支'})
    assert response.status_code == 502
    assert '模型调用失败' in response.json()['detail']
    jobs = c.get('/api/ai/jobs', headers=h).json()
    assert jobs[0]['status'] == '失败' and jobs[0]['task_id'] is None
    assert c.get('/api/records/tasks', headers=h).json()['total'] == before
