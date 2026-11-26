from test_business import client,login
from app import amap
from app.core import settings
def test_map_config_and_proxy_isolation(client,monkeypatch):
    c=client;h=login(c)
    monkeypatch.setattr(settings,'amap_key','test-key');monkeypatch.setattr(settings,'amap_security_code','private-test-code')
    assert c.get('/api/amap/config').status_code==401
    r=c.get('/api/amap/config',headers=h);assert r.status_code==200 and 'private-test-code' not in r.text
    assert r.json()['service_host']=='/_AMapService'
    assert c.get('/api/amap/_AMapService/v3/weather/weatherInfo').status_code==404
    assert c.get('/api/amap/_AMapService/https://example.com').status_code==404
    captured=[]
    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url,params):
            captured.append((url,params))
            class Result:
                status_code=200;content=b'{"status":"1"}';headers={'content-type':'application/json'}
            return Result()
    monkeypatch.setattr(amap.httpx,'AsyncClient',FakeClient)
    r=c.get('/_AMapService/v3/geocode/geo?address=test&key=attacker&jscode=attacker')
    assert r.status_code==200 and captured[0][0]=='https://restapi.amap.com/v3/geocode/geo'
    assert captured[0][1]['key']=='test-key' and captured[0][1]['jscode']=='private-test-code'
    assert 'private-test-code' not in r.text
