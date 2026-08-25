import secrets as _secrets

from fastapi import Depends, HTTPException, Request

from .browser_login import BrowserLogin
from .config import Settings, get_settings
from .pbx_client import PBXClient
from .session_store import SessionStore

_store: SessionStore | None = None
_client: PBXClient | None = None
_browser_login: BrowserLogin | None = None


def get_store(settings: Settings = Depends(get_settings)) -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(settings.data_dir)
    return _store


def get_pbx_client(
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> PBXClient:
    global _client
    if _client is None:
        _client = PBXClient(settings, store)
    return _client


def get_browser_login(
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> BrowserLogin:
    global _browser_login
    if _browser_login is None:
        _browser_login = BrowserLogin(settings, store)
    return _browser_login


def current_browser_login() -> BrowserLogin | None:
    """Уже созданный менеджер входа (для lifespan shutdown, вне DI)."""
    return _browser_login


def current_client() -> PBXClient | None:
    """Уже созданный клиент (для lifespan shutdown, вне DI)."""
    return _client


async def require_api_key(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Проверка ключа нашего API (заголовок X-API-Key)."""
    key = request.headers.get("x-api-key", "")
    if not settings.api_key or not _secrets.compare_digest(key, settings.api_key):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")
