from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'

def test_ready():
    response = client.get('/ready')
    assert response.status_code == 200
    assert response.json() == {'status': 'ready'}

def test_api_root_capabilities():
    response = client.get('/api/v1')
    assert response.status_code == 200
    body = response.json()
    assert body['version'] == 'v1'
    assert 'agents' in body['capabilities']
    assert 'mcp' in body['capabilities']
