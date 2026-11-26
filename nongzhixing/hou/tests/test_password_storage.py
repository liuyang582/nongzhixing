from test_business import client,login
from app.core import SessionLocal,User
from app.passwords import password_store
from sqlalchemy import select

def test_plaintext_creation_change_reset_and_legacy_migration(client):
    c=client;h=login(c)
    with SessionLocal() as db:
        farmer=db.scalar(select(User).where(User.username=='farmer'))
        assert farmer.password=='demo123'
        farmer.password=password_store.legacy.hash('legacyPassword123')
        db.commit()
    legacy=login(c,'farmer','legacyPassword123')
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username=='farmer')).password=='legacyPassword123'
    assert c.post('/api/auth/password',headers=legacy,json={'old_password':'legacyPassword123','new_password':'changedPassword123'}).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username=='farmer')).password=='changedPassword123'
    admin=login(c,'admin')
    created=c.post('/api/admin/users',headers=admin,json={'username':'plainuser','name':'测试账号','password':'plainPassword123','role':'farmer','org':'测试主体','district':'测试乡镇'})
    assert created.status_code==200
    uid=created.json()['id']
    assert c.post(f'/api/admin/users/{uid}/password',headers=admin,json={'new_password':'resetPassword123'}).status_code==200
    with SessionLocal() as db:
        assert db.get(User,uid).password=='resetPassword123'
    assert 'resetPassword123' not in c.get('/api/admin/audit',headers=admin).text
