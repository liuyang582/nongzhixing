"""验证真实本机 Redis 和天气缓存，不输出账号密码、令牌或模型密钥。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from redis import Redis
from app.core import settings

cache=Redis.from_url(settings.redis_url,socket_connect_timeout=3,socket_timeout=3)
assert cache.ping()
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30) as client:
    login=client.post('/api/auth/login',json={'username':'farmer','password':settings.demo_password})
    login.raise_for_status()
    headers={'Authorization':'Bearer '+login.json()['token']}
    first=client.get('/api/weather',params={'latitude':30.27,'longitude':120.15},headers=headers)
    first.raise_for_status()
    second=client.get('/api/weather',params={'latitude':30.27,'longitude':120.15},headers=headers)
    second.raise_for_status()
    assert second.json()['cached'] is True
    assert first.json()['current']==second.json()['current']
    print('Redis PING: OK')
    print('First weather query cached:',first.json()['cached'])
    print('Second weather query cached:',second.json()['cached'])
    print('Weather source:',second.json()['source'])
    print('DB1 weather cache TTL:',cache.ttl('nx:weather:30.270:120.150'))
