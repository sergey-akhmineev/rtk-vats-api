"""Тесты SSO-входа: роуты /auth/login, /auth/code, /auth/cancel и разбор состояния.

Playwright здесь не запускается — менеджер входа подменяется заглушкой,
проверяется контракт роутов и маппинг ошибок.
"""

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.browser_login import BrowserLoginError, BrowserLoginUnavailable
from app.main import app

KEY = {"X-API-Key": "test-key"}


class FakeLogin:
    """Заглушка BrowserLogin: помнит вызовы, отдаёт заданные ответы."""

    def __init__(self, start_result=None, code_result=None, error=None):
        self.start_result = start_result or {"status": "code_required", "hint": "код на +7 999 …"}
        self.code_result = code_result or {"status": "ok", "expires_at": 123, "seconds_left": 1400}
        self.error = error
        self.calls: list[tuple] = []

    async def start(self, username, password="", by_code=False):
        self.calls.append(("start", username, bool(password), by_code))
        if self.error:
            raise self.error
        return self.start_result

    async def submit_code(self, code):
        self.calls.append(("code", code))
        if self.error:
            raise self.error
        return self.code_result

    async def cancel(self):
        self.calls.append(("cancel",))
        return {"status": "cancelled"}

    def status(self):
        return {"code_pending": False, "seconds_to_enter_code": 0, "code_hint": None}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.config import Settings, get_settings

    settings = Settings(
        api_key="test-key",
        pbx_username="lk_user",
        pbx_password="secret",
        data_dir=str(tmp_path),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    deps._store = None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def use_login(fake: FakeLogin) -> None:
    app.dependency_overrides[deps.get_browser_login] = lambda: fake


def test_login_returns_code_required_and_uses_config_creds(client):
    fake = FakeLogin()
    use_login(fake)
    r = client.post("/auth/login", json={}, headers=KEY)
    assert r.status_code == 200
    assert r.json()["status"] == "code_required"
    # креды взяты из конфигурации, пароль передан
    assert fake.calls[0] == ("start", "lk_user", True, False)


def test_login_accepts_explicit_credentials(client):
    fake = FakeLogin()
    use_login(fake)
    r = client.post("/auth/login", json={"username": "other", "password": "pw"}, headers=KEY)
    assert r.status_code == 200
    assert fake.calls[0] == ("start", "other", True, False)


def test_login_by_code_does_not_send_password(client):
    fake = FakeLogin(start_result={"status": "code_required"})
    use_login(fake)
    client.post("/auth/login", json={"by_code": True}, headers=KEY)
    assert fake.calls[0] == ("start", "lk_user", False, True)


def test_code_completes_session(client):
    fake = FakeLogin()
    use_login(fake)
    r = client.post("/auth/code", json={"code": "123456"}, headers=KEY)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert fake.calls[0] == ("code", "123456")


def test_login_error_maps_to_400(client):
    use_login(FakeLogin(error=BrowserLoginError("Паспорт отклонил вход")))
    r = client.post("/auth/login", json={}, headers=KEY)
    assert r.status_code == 400
    assert "Паспорт" in r.json()["detail"]


def test_missing_playwright_maps_to_501(client):
    use_login(FakeLogin(error=BrowserLoginUnavailable("Не установлен playwright")))
    r = client.post("/auth/login", json={}, headers=KEY)
    assert r.status_code == 501


def test_cancel(client):
    fake = FakeLogin()
    use_login(fake)
    assert client.post("/auth/cancel", headers=KEY).json() == {"status": "cancelled"}


def test_status_includes_login_state(client):
    use_login(FakeLogin())
    body = client.get("/auth/status", headers=KEY).json()
    for field in ("authenticated", "has_fingerprint", "code_pending", "seconds_to_enter_code"):
        assert field in body


def test_auth_routes_require_api_key(client):
    use_login(FakeLogin())
    assert client.post("/auth/login", json={}).status_code == 401
    assert client.post("/auth/code", json={"code": "1"}).status_code == 401
