"""只对 8001 隔离环境操作，保存逐模块验收证据和导出文件。"""
import io
import json
from pathlib import Path
import httpx
from openpyxl import load_workbook

OUT = Path(__file__).resolve().parents[2] / 'outputs/final-acceptance'
OUT.mkdir(exist_ok=True)
evidence = []
session = json.loads((OUT.parent / 'browser-acceptance-session.json').read_text(encoding='utf-8'))
assert session['backend_port'] == 8001 and session['database'] == 'SQLite'
test_password = Path(session['credential_file']).read_text(encoding='utf-8')


def record(name, passed, detail=''):
    evidence.append({'check': name, 'passed': bool(passed), 'detail': detail})


with httpx.Client(base_url='http://127.0.0.1:8001/api', timeout=30) as c:
    health = c.get('/health').json()
    # 通过隔离进程标识确认目标，禁止对主服务运行。
    assert '测试桩' in str(health), '目标不是隔离验收服务'
    login = c.post('/auth/login', json={'username': 'farmer', 'password': test_password})
    login.raise_for_status()
    c.headers['Authorization'] = 'Bearer ' + login.json()['token']
    modules = []
    tokens = {}
    for role in ['farmer', 'regulator', 'admin']:
        response = c.post('/auth/login', json={'username': role, 'password': test_password})
        response.raise_for_status()
        c.headers['Authorization'] = 'Bearer ' + response.json()['token']
        tokens[role] = c.headers['Authorization']
        modules.extend({**m, 'acceptance_role': role} for m in c.get('/modules').json())
    (OUT / 'modules.json').write_text(json.dumps(modules, ensure_ascii=False, indent=2), encoding='utf-8')
    for module in modules:
        role = module['acceptance_role']
        c.headers['Authorization'] = tokens[role]
        mid = module['id']
        label = role + '/' + mid
        rows = c.get('/records/' + mid).json()['items']
        data = {f['key']: (1 if f['type'] == 'number' else '2026-10-02' if f['type'] == 'date' else f['options'][0] if f['options'] else '隔离验收合成资料') for f in module['fields'] if f['required']}
        data.update(rows[0]['data'] if rows else {})
        # 通用新增台账不能复制 AI 来源标记；AI 任务只能经确认接口创建。
        if mid == 'tasks':
            data.pop('ai_job_id', None)
        if any(f['key'] == 'note' for f in module['fields']):
            data['note'] = '最终隔离验收合成记录'
        title = '最终验收-' + mid
        created = c.post('/records/' + mid, json={'title': title, 'status': '待处理', 'data': data})
        record(label + ':新增', created.status_code == 200, str(created.status_code) if created.status_code == 200 else str(created.json().get('detail')))
        if created.status_code != 200:
            continue
        row = created.json()
        changed = c.put(f"/records/{mid}/{row['id']}", json={'title': title + '-编辑', 'status': '已完成', 'data': data, 'version': row['version']})
        record(mid + ':编辑', changed.status_code == 200, str(changed.status_code))
        queried = c.get('/records/' + mid, params={'q': title, 'status': '已完成'}).json()
        record(mid + ':标题与状态筛选', queried['total'] == 1)
        for fmt, path in [('csv', f'/records/{mid}/export/csv'), ('xlsx', f'/reports/{mid}/xlsx'), ('pdf', f'/reports/{mid}/pdf')]:
            response = c.get(path)
            valid = response.status_code == 200
            if valid and fmt == 'xlsx':
                wb = load_workbook(io.BytesIO(response.content))
                valid = wb.active.max_row >= 2
            if valid and fmt == 'pdf':
                valid = response.content.startswith(b'%PDF') and b'%%EOF' in response.content[-100:]
            if valid:
                (OUT / (mid + '.' + fmt)).write_bytes(response.content)
            record(mid + ':' + fmt + '导出落盘', valid, str(response.status_code))
        deleted = c.delete(f"/records/{mid}/{row['id']}")
        record(mid + ':删除', deleted.status_code == 200, str(deleted.status_code))
        if deleted.status_code == 200:
            record(mid + ':删除后查询', c.get('/records/' + mid, params={'q': title}).json()['total'] == 0)

(OUT / 'interfaces.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'total': len(evidence), 'passed': sum(x['passed'] for x in evidence),
                  'failed': [x for x in evidence if not x['passed']]}, ensure_ascii=False))
