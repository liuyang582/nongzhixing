"""通过前端代理检查三个角色的读取接口；不改变业务状态或账号密码。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from app.core import settings

results=[]
def check(c,path,role,expected=200):
    r=c.get(path)
    ok=r.status_code==expected
    results.append((role,path.split('?')[0],r.status_code,ok))
    return r

with httpx.Client(base_url='http://127.0.0.1:5173',timeout=25) as c:
    check(c,'/api/health','公共')
    for role in ['farmer','regulator','admin']:
        r=c.post('/api/auth/login',json={'username':role,'password':settings.demo_password})
        r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['token']
        for path in ['/auth/me','/dashboard','/notifications','/files','/ai/jobs','/crops','/crop-guides']:
            check(c,'/api'+path,role)
        modules=check(c,'/api/modules',role).json()
        for module in modules:
            check(c,'/api/records/'+module['id'],role)
            check(c,'/api/records/'+module['id']+'/export/csv',role)
        if role!='admin':
            check(c,'/api/stocks',role);check(c,'/api/orders',role)
            lands=check(c,'/api/records/lands?size=200',role).json()['items']
            for land in lands:
                check(c,f'/api/plots/{land["id"]}/flow',role)
                check(c,f'/api/plots/{land["id"]}/timeline',role)
            located=next((l for l in lands if l['data'].get('latitude')),None)
            if located:check(c,f'/api/plots/{located["id"]}/weather',role)
            check(c,'/api/amap/config',role)
        if role=='farmer':
            for path in ['/finance','/environment-rules','/traces','/reports/harvest/xlsx','/reports/harvest/pdf','/finance/export/xlsx','/finance/export/pdf']:
                check(c,'/api'+path,role)
            traces=check(c,'/api/traces',role).json()
            for trace in traces:
                check(c,f'/api/traces/{trace["id"]}/qr',role)
                check(c,'/api/public/trace/'+trace['token'],role,200 if trace['published'] else 404)
            # 使用 JS SDK 的请求标识；Web 端 Key 不能按普通 REST Key 探测。
            response=check(c,'/_AMapService/v3/geocode/geo?s=rsv3&address=浙江省杭州市余杭区',role)
            results.append((role,'高德地址搜索返回值',response.status_code,
                            response.status_code==200 and response.json().get('status')=='1'))
        if role=='admin':
            check(c,'/api/admin/users',role);check(c,'/api/admin/audit',role)

failed=[x for x in results if not x[3]]
output=Path(__file__).resolve().parents[2]/'outputs'/'接口联通检查.md'
lines=['# 农知行接口联通检查','',f'通过：{len(results)-len(failed)} / {len(results)}。检查通过 http://127.0.0.1:5173 的前端代理调用实际后端。','',
       '本次检查读取、台账 CSV、代表性 Excel/PDF、二维码、天气与高德搜索；未公开溯源的 404 是预期行为。没有切换账号状态、修改密码、发布溯源或新增生产记录。登录和导出按系统设计写审计日志。','',
       'AI 外部模型本次未重复调用；新增、编辑、删除、库存事务、任务确认和密码变更使用隔离测试验证，不等于所有页面按钮已做完整浏览器验收。','',
       '|角色|接口|状态|结果|','|---|---|---|---|']
for role,path,status,ok in results:
    # 公开随机码不写入报告。
    if '/public/trace/' in path:path='/api/public/trace/{token}'
    lines.append(f'|{role}|{path}|{status}|'+('通过' if ok else '失败')+'|')
output.write_text('\n'.join(lines),encoding='utf-8')
print(f'Checks: {len(results)}, passed: {len(results)-len(failed)}, failed: {len(failed)}')
for role,path,status,ok in failed:print(role,path,status)
if failed:raise SystemExit(1)
