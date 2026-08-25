import time

import httpx
import pytest
import respx

from app.config import Settings
from app.pbx_client import PBXAuthRequired, PBXClient
from app.session_store import SessionStore
from tests.conftest import AUTH_2FA_RESPONSE, make_jwt

BASE = "https://p2.cloudpbx.rt.ru/webapi"


def make_client(tmp_path) -> tuple[PBXClient, SessionStore]:
    settings = Settings(
        pbx_base_url="https://p2.cloudpbx.rt.ru",
        pbx_username="admin",
        pbx_password="secret",
        pbx_domain="000000.00.rt.ru",
        data_dir=str(tmp_path),
    )
    store = SessionStore(str(tmp_path))
    return PBXClient(settings, store), store


@respx.mock
async def test_auth_start_2fa(tmp_path):
    respx.post(f"{BASE}/auth").mock(return_value=httpx.Response(200, json=AUTH_2FA_RESPONSE))
    client, store = make_client(tmp_path)

    result = await client.auth_start()

    assert result == {"status": "sms_required"}
    assert store.two_factor_session == "2fa-session-abc"
    assert store.token is None
    await client.close()


@respx.mock
async def test_auth_complete_saves_tokens(tmp_path):
    jwt = make_jwt()
    respx.post(f"{BASE}/auth").mock(
        return_value=httpx.Response(200, json={"token": jwt, "refresh_token": "rt-1"})
    )
    client, store = make_client(tmp_path)
    store.save_two_factor_session("2fa-session-abc")

    result = await client.auth_complete("123456")

    assert result["status"] == "ok"
    assert store.token == jwt
    assert store.refresh_token == "rt-1"
    assert store.is_authenticated()
    # two_factor_session очищена после успешного логина
    assert store.two_factor_session is None

    # проверяем, что в форме ушли session и code
    sent = respx.calls[0].request.content.decode()
    assert "two_factor_session=2fa-session-abc" in sent
    assert "two_factor_code=123456" in sent
    await client.close()


@respx.mock
async def test_auth_complete_without_start(tmp_path):
    client, _ = make_client(tmp_path)
    with pytest.raises(PBXAuthRequired):
        await client.auth_complete("123456")
    await client.close()


@respx.mock
async def test_request_refreshes_expired_token(tmp_path):
    new_jwt = make_jwt()
    respx.post(f"{BASE}/auth/refresh_token").mock(
        return_value=httpx.Response(200, json={"token": new_jwt, "refresh_token": "rt-2"})
    )
    route = respx.get(f"{BASE}/domain/contacts").mock(return_value=httpx.Response(200, json=[]))

    client, store = make_client(tmp_path)
    store.save_tokens(make_jwt(exp=int(time.time()) - 100), "rt-1")

    resp = await client.request("GET", "/domain/contacts")

    assert resp.status_code == 200
    assert store.token == new_jwt
    assert store.refresh_token == "rt-2"
    # в запросе ушёл новый токен
    assert route.calls[0].request.headers["authorization"] == f"Bearer {new_jwt}"
    await client.close()


@respx.mock
async def test_request_retries_after_401(tmp_path):
    fresh_jwt = make_jwt()
    respx.post(f"{BASE}/auth/refresh_token").mock(
        return_value=httpx.Response(200, json={"token": fresh_jwt, "refresh_token": "rt-3"})
    )
    # первый запрос со старым токеном -> 401, после refresh -> 200
    route = respx.get(f"{BASE}/domain/contacts").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=[{"id": 1}])]
    )

    client, store = make_client(tmp_path)
    store.save_tokens(make_jwt(), "rt-old")

    resp = await client.request("GET", "/domain/contacts")

    assert resp.status_code == 200
    assert resp.json() == [{"id": 1}]
    assert route.call_count == 2
    await client.close()


@respx.mock
async def test_request_without_session_raises(tmp_path):
    client, _ = make_client(tmp_path)
    with pytest.raises(PBXAuthRequired):
        await client.request("GET", "/domain/contacts")
    await client.close()


@respx.mock
async def test_session_persists_to_disk(tmp_path):
    jwt = make_jwt()
    respx.post(f"{BASE}/auth").mock(
        return_value=httpx.Response(200, json={"token": jwt, "refresh_token": "rt-1"})
    )
    client, store = make_client(tmp_path)
    store.save_two_factor_session("s")
    await client.auth_complete("000000")
    await client.close()

    # новый инстанс читает сессию с диска
    store2 = SessionStore(str(tmp_path))
    assert store2.token == jwt
    assert store2.is_authenticated()
