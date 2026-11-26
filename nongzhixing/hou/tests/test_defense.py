import io
from datetime import date
from openpyxl import load_workbook
from test_business import client, login, another_farmer
from test_flow import prepare

def test_configured_alerts_and_timeline(client):
    c=client;h=login(c);land,g,env=prepare(c,h)
    body={'plot_id':land['id'],'crop':'番茄','stage':'开花结果期','temperature_min':10,'temperature_max':40,'humidity_min':0,'humidity_max':100,'soil_min':50,'soil_max':100,'basis':'隔离测试阈值，不是种植建议'}
    bad={**body,'soil_min':90,'soil_max':10}
    assert c.post('/api/environment-rules',headers=h,json=bad).status_code==422
    r=c.post('/api/environment-rules',headers=h,json=body);assert r.status_code==200
    rid=r.json()['id']
    assert c.get('/api/environment-rules',headers=another_farmer(c)).json()==[]
    for _ in range(2):
        assert c.post('/api/records/environment',headers=h,json={'title':'阈值测试','data':env['data']}).status_code==200
    alerts=c.get('/api/records/alerts?size=200',headers=h).json()['items']
    own=[a for a in alerts if a['data'].get('rule_id')==rid];assert len(own)==1
    a=own[0]
    assert c.put('/api/records/alerts/'+str(a['id']),headers=h,json={'title':a['title'],'version':a['version'],'status':'已关闭','data':{**a['data'],'note':'现场核查并记录处理'}}).status_code==200
    c.post('/api/records/environment',headers=h,json={'title':'再测量','data':env['data']})
    assert len([a for a in c.get('/api/records/alerts?size=200',headers=h).json()['items'] if a['data'].get('rule_id')==rid])==2
    timeline=c.get(f"/api/plots/{land['id']}/timeline?growth_id={g['id']}",headers=h)
    assert timeline.status_code==200 and {'growth','environment','alerts'}<=set(e['kind'] for e in timeline.json())
    assert c.get(f"/api/plots/{land['id']}/timeline",headers=login(c,'other','testpass123')).status_code==404

def test_harvest_stock_trace_and_finance(client):
    c=client;h=login(c);land,g,_=prepare(c,h)
    body={'growth_id':g['id'],'batch':'TEST-BATCH','date':date.today().isoformat(),'quantity':10,'grade':'A'}
    assert c.post('/api/harvests',headers=h,json={**body,'quantity':0}).status_code==422
    harvest=c.post('/api/harvests',headers=h,json=body).json()
    result=c.post(f"/api/harvests/{harvest['id']}/stock",headers=h);assert result.status_code==200
    assert c.post(f"/api/harvests/{harvest['id']}/stock",headers=h).status_code==409
    assert c.delete(f"/api/records/harvest/{harvest['id']}",headers=h).status_code==409
    assert c.delete(f"/api/records/growth/{g['id']}",headers=h).status_code==409
    trace=c.get('/api/traces',headers=h).json()[0]
    url='/api/public/trace/'+trace['token']
    assert c.get(url).status_code==404
    other=another_farmer(c)
    assert c.post(f"/api/traces/{trace['id']}/publish",headers=other).status_code==404
    assert c.post(f"/api/traces/{trace['id']}/publish",headers=h).status_code==200
    data=c.get(url).json();assert data['batch']=='TEST-BATCH' and 'latitude' not in data and 'assignee' not in str(data)
    qr=c.get(f"/api/traces/{trace['id']}/qr",headers=h);assert qr.content.startswith(b'\x89PNG')
    oid=c.post('/api/orders',headers=h,json={'stock_id':result.json()['stock_id'],'customer':'测试客户','quantity':2,'price':3.25}).json()['id']
    assert c.post(f'/api/orders/{oid}/ship',headers=h).status_code==200
    for amount in [0.1,0.2]:
        r=c.post('/api/records/expenses',headers=h,json={'title':'人工投入','data':{'plot_id':land['id'],'plot':land['title'],'date':date.today().isoformat(),'category':'人工','cost':amount,'note':'测试费用凭据'}})
        assert r.status_code==200,r.text
    fin=c.get('/api/finance',headers=h).json();assert fin['cost']==0.3 and fin['sales']==6.5 and fin['profit']==6.2
    assert c.get('/api/finance',headers=other).json()['cost']==0
    assert c.get('/api/finance',headers=login(c,'regulator')).status_code==403
    for fmt in ['xlsx','pdf']:
        exported=c.get('/api/finance/export/'+fmt,headers=h);assert exported.status_code==200
    assert c.get('/api/finance/export/pdf',headers=other).status_code==200
    c.post(f"/api/traces/{trace['id']}/publish",headers=h)
    assert c.get(url).status_code==404

def test_password_revocation_and_exports(client):
    c=client;h=login(c)
    c.post('/api/records/tasks',headers=h,json={'title':'=1+1','data':{'type':'巡检'}})
    x=c.get('/api/reports/tasks/xlsx',headers=h);assert x.status_code==200
    wb=load_workbook(io.BytesIO(x.content));assert any(row[0]=="'=1+1" for row in wb.active.iter_rows(values_only=True))
    pdf=c.get('/api/reports/tasks/pdf',headers=h);assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert c.get('/api/reports/users/pdf',headers=h).status_code in (403,404)
    assert c.post('/api/auth/password',headers=h,json={'old_password':'wrong','new_password':'newpassword123'}).status_code==400
    assert c.post('/api/auth/password',headers=h,json={'old_password':'demo123','new_password':'newpassword123'}).status_code==200
    assert c.get('/api/auth/me',headers=h).status_code==401
    assert c.post('/api/auth/login',json={'username':'farmer','password':'demo123'}).status_code==401
    new=login(c,'farmer','newpassword123');assert c.get('/api/notifications',headers=new).status_code==200
    admin=login(c,'admin');uid=c.get('/api/auth/me',headers=new).json()['id']
    assert c.post(f'/api/admin/users/{uid}/password',headers=new,json={'new_password':'resetpass123'}).status_code==403
    assert c.post(f'/api/admin/users/{uid}/password',headers=admin,json={'new_password':'resetpass123'}).status_code==200
    assert c.get('/api/auth/me',headers=new).status_code==401
    logs=c.get('/api/admin/audit',headers=admin).text
    assert 'newpassword123' not in logs and 'resetpass123' not in logs
    guides=c.get('/api/crop-guides',headers=admin).json();assert len(guides)==3 and all(g['source'].startswith('https://') for g in guides)
