import os

import httpx
import pytest
import respx

os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("PBX_DOMAIN", "000000.00.rt.ru")
os.environ.setdefault("PBX_PASSWORD", "secret")
os.environ.setdefault("PBX_VERIFY_SSL", "true")

from app.config import get_settings  # noqa: E402
from app.deps import get_pbx_client, get_store  # noqa: E402
from app.main import app  # noqa: E402
from app.pbx_client import PBXClient  # noqa: E402
from app.session_store import SessionStore  # noqa: E402
from tests.conftest import make_jwt  # noqa: E402

BASE = "https://p2.cloudpbx.rt.ru/webapi"
KEY = {"X-API-Key": "test-api-key"}


@pytest.fixture
def client(tmp_path):
    store = SessionStore(str(tmp_path))
    store.save_tokens(make_jwt(), "rt-1")
    pbx = PBXClient(get_settings(), store)

    app.dependency_overrides[get_pbx_client] = lambda: pbx
    app.dependency_overrides[get_store] = lambda: store
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


async def test_health_no_key(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_contacts_require_api_key(client):
    resp = await client.get("/contacts")
    assert resp.status_code == 401


@respx.mock
async def test_contacts_with_key(client):
    respx.get(f"{BASE}/domain/contacts").mock(
        return_value=httpx.Response(200, json=[{"id": 0, "name": "Контакты вне групп", "contacts": []}])
    )
    resp = await client.get("/contacts", headers=KEY)
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Контакты вне групп"


@respx.mock
async def test_proxy_passthrough(client):
    route = respx.get(f"{BASE}/domain/contacts/users").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "group"}])
    )
    resp = await client.get("/proxy/domain/contacts/users?foo=bar", headers=KEY)
    assert resp.status_code == 200
    assert route.calls[0].request.url.params["foo"] == "bar"


@respx.mock
async def test_proxy_binary_record(client):
    respx.get(f"{BASE}/domain/call_history/42/record").mock(
        return_value=httpx.Response(200, content=b"RIFF....", headers={"content-type": "audio/wav"})
    )
    resp = await client.get("/calls/42/record", headers=KEY)
    assert resp.status_code == 200
    assert resp.content == b"RIFF...."
    assert resp.headers["content-type"].startswith("audio/wav")


@respx.mock
async def test_create_contact(client):
    route = respx.post(f"{BASE}/domain/contacts").mock(
        return_value=httpx.Response(200, json={"id": 5, "name": "Иванов"})
    )
    resp = await client.post(
        "/contacts",
        headers=KEY,
        json={"name": "Иванов", "numbers": [{"number": "89140000000", "contactType": "mobile"}]},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == 5
    sent = route.calls[0].request
    assert b"Ivanov" not in sent.content  # имя ушло в UTF-8 JSON
    assert sent.headers["content-type"].startswith("application/json")


async def test_auth_status(client):
    resp = await client.get("/auth/status", headers=KEY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["seconds_left"] > 0
