"""在独立 SQLite 中验收账号创建、启停及权限，不修改本地账号。"""
from test_business import client, login


def test_account_creation_toggle_and_access(client):
    c = client
    admin = login(c, "admin")
    farmer = login(c)
    body = {"username": "acceptance_account", "name": "隔离验收账号",
            "password": "acceptance-test-only", "role": "farmer",
            "org": "隔离验收主体", "district": "测试乡镇"}
    assert c.post('/api/admin/users', headers=farmer, json=body).status_code == 403
    created = c.post('/api/admin/users', headers=admin, json=body)
    assert created.status_code == 200
    uid = created.json()['id']
    assert 'password' not in created.json()
    assert c.post('/api/admin/users', headers=admin, json=body).status_code == 409
    session = login(c, body['username'], body['password'])
    assert c.get('/api/auth/me', headers=session).status_code == 200
    assert c.post(f'/api/admin/users/{uid}/toggle', headers=farmer).status_code == 403
    disabled = c.post(f'/api/admin/users/{uid}/toggle', headers=admin)
    assert disabled.status_code == 200 and disabled.json()['active'] is False
    assert c.get('/api/auth/me', headers=session).status_code == 401
    assert c.post('/api/auth/login', json={"username": body['username'], "password": body['password']}).status_code == 401
    enabled = c.post(f'/api/admin/users/{uid}/toggle', headers=admin)
    assert enabled.status_code == 200 and enabled.json()['active'] is True
    renewed = login(c, body['username'], body['password'])
    assert c.get('/api/auth/me', headers=renewed).status_code == 200
    own_id = c.get('/api/auth/me', headers=admin).json()['id']
    assert c.post(f'/api/admin/users/{own_id}/toggle', headers=admin).status_code == 422
    assert body['password'] not in c.get('/api/admin/audit', headers=admin).text
