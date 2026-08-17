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
    assert 'services' in body['capabilities']
    assert 'models' in body['capabilities']


def test_empty_service_registry_without_configuration(monkeypatch):
    for name in ('ASSISTX_BASE_URL', 'SOPHIA_BASE_URL', 'LMSTUDIO_BASE_URL'):
        monkeypatch.delenv(name, raising=False)
    response = client.get('/api/v1/services')
    assert response.status_code == 200
    assert response.json() == {'services': []}


def test_service_registry_does_not_expose_private_base_url(monkeypatch):
    monkeypatch.setenv('ASSISTX_BASE_URL', 'http://assistx.tailnet:8000')
    response = client.get('/api/v1/services')
    assert response.status_code == 200
    service = response.json()['services'][0]
    assert service['id'] == 'assistx'
    assert service['configured'] is True
    assert 'base_url' not in service
    assert 'tailnet' not in str(service).lower()


def test_lmstudio_discovery_redacts_private_url(monkeypatch):
    monkeypatch.setenv('LMSTUDIO_BASE_URL', 'http://models.tailnet:1234')
    response = client.get('/api/v1/models')
    assert response.status_code == 200
    model = response.json()['models'][0]
    assert model == {
        'provider': 'lmstudio',
        'configured': True,
        'availability': 'private',
    }
    assert 'models.tailnet' not in str(response.json())
