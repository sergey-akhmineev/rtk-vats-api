import time

import pytest

from app.config import Settings
from app.pbx_client import PBXClient, PBXError
from app.session_store import SessionStore
from tests.conftest import make_jwt


def make_client(tmp_path) -> PBXClient:
    settings = Settings(data_dir=str(tmp_path))
    return PBXClient(settings, SessionStore(str(tmp_path)))


def test_import_tokens_ok(tmp_path):
    client = make_client(tmp_path)
    jwt = make_jwt(exp=int(time.time()) + 900)
    result = client.import_tokens(jwt, "rt-9", "fp-abc")
    assert result["status"] == "ok"
    assert result["has_refresh_token"] is True
    assert result["seconds_left"] > 800
    assert client.store.token == jwt
    assert client.store.fingerprint == "fp-abc"


def test_import_tokens_not_jwt(tmp_path):
    client = make_client(tmp_path)
    with pytest.raises(PBXError):
        client.import_tokens("not-a-token")


def test_import_tokens_without_refresh(tmp_path):
    client = make_client(tmp_path)
    result = client.import_tokens(make_jwt())
    assert result["status"] == "ok"
    assert result["has_refresh_token"] is False
