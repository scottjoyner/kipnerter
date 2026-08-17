from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SERVICE_VARS = ('ASSISTX_BASE_URL', 'SOPHIA_BASE_URL', 'LMSTUDIO_BASE_URL')


def clear_services(monkeypatch):
    for name in SERVICE_VARS:
        monkeypatch.delenv(name, raising=False)


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
    assert 'gateway' in body['capabilities']


def test_empty_service_registry_without_configuration(monkeypatch):
    clear_services(monkeypatch)
    response = client.get('/api/v1/services')
    assert response.status_code == 200
    assert response.json() == {'services': []}


def test_empty_live_health_without_configuration(monkeypatch):
    clear_services(monkeypatch)
    response = client.get('/api/v1/services/health')
    assert response.status_code == 200
    assert response.json() == {'services': []}


def test_service_registry_does_not_expose_private_base_url(monkeypatch):
    clear_services(monkeypatch)
    monkeypatch.setenv('ASSISTX_BASE_URL', 'http://assistx.tailnet:8000')
    response = client.get('/api/v1/services')
    assert response.status_code == 200
    service = response.json()['services'][0]
    assert service['id'] == 'assistx'
    assert service['configured'] is True
    assert 'base_url' not in service
    assert 'tailnet' not in str(service).lower()


def test_sophia_uses_root_health_surface(monkeypatch):
    clear_services(monkeypatch)
    monkeypatch.setenv('SOPHIA_BASE_URL', 'http://sophia.tailnet:8765')
    response = client.get('/api/v1/services')
    assert response.status_code == 200
    assert response.json()['services'][0]['health_path'] == '/'


def test_lmstudio_discovery_redacts_private_url(monkeypatch):
    clear_services(monkeypatch)
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


def test_gateway_advertises_only_allowlisted_routes():
    response = client.get('/api/v1/gateway/routes')
    assert response.status_code == 200
    body = response.json()
    assert body['authentication'] == 'bearer'
    text = str(body)
    assert '/v1/chat/completions' in text
    assert '/v1/models' in text
    assert 'proxy' not in text.lower()


def test_gateway_fails_closed_when_auth_not_configured(monkeypatch):
    clear_services(monkeypatch)
    monkeypatch.setenv('LMSTUDIO_BASE_URL', 'http://models.tailnet:1234')
    monkeypatch.delenv('KIPNERTER_GATEWAY_TOKEN', raising=False)
    response = client.get('/api/v1/gateway/lmstudio/v1/models')
    assert response.status_code == 503
    assert response.json()['detail'] == 'gateway authentication is not configured'


def test_gateway_rejects_invalid_bearer_token(monkeypatch):
    clear_services(monkeypatch)
    monkeypatch.setenv('LMSTUDIO_BASE_URL', 'http://models.tailnet:1234')
    monkeypatch.setenv('KIPNERTER_GATEWAY_TOKEN', 'expected-token')
    response = client.get(
        '/api/v1/gateway/lmstudio/v1/models',
        headers={'Authorization': 'Bearer wrong-token'},
    )
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'


def test_gateway_denies_non_allowlisted_tailnet_paths(monkeypatch):
    clear_services(monkeypatch)
    monkeypatch.setenv('ASSISTX_BASE_URL', 'http://assistx.tailnet:8000')
    monkeypatch.setenv('KIPNERTER_GATEWAY_TOKEN', 'operator-token')
    response = client.get(
        '/api/v1/gateway/assistx/openapi.json',
        headers={'Authorization': 'Bearer operator-token'},
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'gateway route is not available'
