"""本机合成演示联调。保留演示记录，不修改账号密码或公开生产资料。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select
from app.core import settings,SessionLocal,Record,Trace
out=Path(__file__).resolve().parents[2]/'outputs';out.mkdir(exist_ok=True)
with httpx.Client(base_url='http://127.0.0.1:8000/api',timeout=30) as c:
    r=c.post('/auth/login',json={'username':'farmer','password':settings.demo_password});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['token']
    with SessionLocal() as db:
        g=db.scalar(select(Record).where(Record.module=='growth',Record.title=='联调演示·秋季番茄批次'))
        if not g:raise RuntimeError('缺少此前的合成演示生长记录')
        gid=g.id;lid=g.data['plot_id'];crop=g.data['crop'];stage=g.data['stage']
        e=db.scalar(select(Record).where(Record.module=='expenses',Record.title=='答辩联调演示·人工支出'))
        h=db.scalar(select(Record).where(Record.module=='harvest',Record.title=='番茄采收 DEMO-20261002'))
    if not e:
        r=c.post('/records/expenses',json={'title':'答辩联调演示·人工支出','data':{'plot_id':lid,'plot':'联调演示·番茄地块','date':'2026-10-02','category':'人工','cost':120,'note':'合成演示费用，未发生实际支出'}});r.raise_for_status()
        with SessionLocal() as db:
            e=db.get(Record,r.json()['id']);e.demo=True;db.commit()
    if not h:
        r=c.post('/harvests',json={'growth_id':gid,'batch':'DEMO-20261002','date':'2026-10-02','quantity':20,'grade':'A'});r.raise_for_status();hid=r.json()['id']
    else:hid=h.id
    with SessionLocal() as db:existing=db.scalar(select(Trace).where(Trace.harvest_id==hid))
    if not existing:
        r=c.post(f'/harvests/{hid}/stock');r.raise_for_status()
    assert c.post(f'/harvests/{hid}/stock').status_code==409
    timeline=c.get(f'/plots/{lid}/timeline');timeline.raise_for_status();assert any(e['kind']=='harvest' for e in timeline.json())
    fin=c.get('/finance');fin.raise_for_status();assert not any(x['title']=='答辩联调演示·人工支出' for x in fin.json()['costs'])
    assert any(x['title']=='答辩联调演示·人工支出' for x in c.get('/finance?include_demo=true').json()['costs'])
    for path,name in [('/reports/harvest/xlsx','采收演示.xlsx'),('/reports/harvest/pdf','采收演示.pdf'),('/finance/export/pdf?include_demo=true','经营演示.pdf')]:
        r=c.get(path);r.raise_for_status();(out/name).write_bytes(r.content)
    for path in ['/environment-rules','/notifications','/crop-guides','/traces']:
        r=c.get(path);r.raise_for_status();print(path, 'OK',len(r.json()))
    print('MySQL 关联采收、一次入库、时间轴、演示隔离及文件导出：通过。溯源保持未公开。')
