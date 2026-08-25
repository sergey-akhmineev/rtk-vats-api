"""Авторизация в ВАТС.

Три способа получить сессию — от самого удобного к запасному:

1. **SSO «Ростелеком Паспорт»** (`/auth/login` + `/auth/code`) — основной для доменов,
   подключённых к Паспорту (у них классический вход логином/паролем не работает вовсе).
   Логин/пароль → SMS с одноразовым кодом → токены. Требует playwright.
2. **Классический вход** (`/auth/start` + `/auth/complete`) — для доменов со «своим»
   паролем в самой ВАТС: `POST /webapi/auth` + при необходимости код из SMS.
3. **Импорт токенов** (`/auth/import`) — ручной обход: пользователь копирует token,
   refreshToken и fingerprint из браузера, где он уже залогинен.

Дальше сессию держит фоновый keepalive (`app/keepalive.py`).
"""

from fastapi import APIRouter, Depends

from ..browser_login import BrowserLogin
from ..config import Settings, get_settings
from ..deps import get_browser_login, get_pbx_client, get_store
from ..models import LoginRequest, SmsCode, TokenImport
from ..pbx_client import PBXClient
from ..session_store import SessionStore
from ._common import map_errors

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def auth_login(
    body: LoginRequest,
    login: BrowserLogin = Depends(get_browser_login),
    settings: Settings = Depends(get_settings),
):
    """Шаг 1 SSO: логин+пароль в «Ростелеком Паспорт». Отправляет SMS с кодом.

    Возвращает `status="code_required"` (ждём `/auth/code`) либо сразу `status="ok"`,
    если Паспорт не запросил второй фактор. Учётные данные можно не передавать —
    тогда берутся `PBX_USERNAME` / `PBX_PASSWORD` из конфигурации.
    """
    try:
        return await login.start(
            username=body.username or settings.pbx_username,
            password="" if body.by_code else (body.password or settings.pbx_password),
            by_code=body.by_code,
        )
    except Exception as exc:
        raise map_errors(exc)


@router.post("/code")
async def auth_code(body: SmsCode, login: BrowserLogin = Depends(get_browser_login)):
    """Шаг 2 SSO: одноразовый код из SMS. После успеха сессия готова к работе.

    Код спрашивать у пользователя — не подставлять и не угадывать.
    """
    try:
        return await login.submit_code(body.code)
    except Exception as exc:
        raise map_errors(exc)


@router.post("/cancel")
async def auth_cancel(login: BrowserLogin = Depends(get_browser_login)):
    """Закрыть незавершённую попытку входа (например, если SMS не пришла)."""
    try:
        return await login.cancel()
    except Exception as exc:
        raise map_errors(exc)


@router.post("/start")
async def auth_start(client: PBXClient = Depends(get_pbx_client)):
    """Классический вход: логин/пароль/домен из конфигурации.

    Работает только там, где у учётной записи есть собственный пароль ВАТС.
    Для SSO-доменов отвечает «Введенные учетные данные некорректны» — там нужен `/auth/login`.
    """
    try:
        return await client.auth_start()
    except Exception as exc:
        raise map_errors(exc)


@router.post("/complete")
async def auth_complete(body: SmsCode, client: PBXClient = Depends(get_pbx_client)):
    """Классический вход, шаг 2: код из SMS."""
    try:
        return await client.auth_complete(body.code)
    except Exception as exc:
        raise map_errors(exc)


@router.post("/import")
async def auth_import(body: TokenImport, client: PBXClient = Depends(get_pbx_client)):
    """Импорт токенов из браузера (запасной путь, если браузерный вход недоступен).

    DevTools → Application → Local Storage → `token`, `refreshToken`.
    `fingerprint` в хранилище отсутствует — берётся из адресной строки SSO-редиректа
    (`…&fingerprint=…`) либо `getBrowserFingerprint()` в консоли ЛК. Без него
    обновление сессии работать не будет.
    """
    try:
        return client.import_tokens(body.token, body.refresh_token, body.fingerprint)
    except Exception as exc:
        raise map_errors(exc)


@router.post("/refresh")
async def auth_refresh(client: PBXClient = Depends(get_pbx_client), store: SessionStore = Depends(get_store)):
    """Обновить JWT прямо сейчас (обычно это делает фоновый keepalive).

    Полезно для проверки, что refresh_token и fingerprint рабочие.
    """
    try:
        await client.refresh(force=True)
        return {
            "status": "ok",
            "expires_at": store.expires_at,
            "seconds_left": store.seconds_left(),
        }
    except Exception as exc:
        raise map_errors(exc)


@router.get("/status")
async def auth_status(
    store: SessionStore = Depends(get_store),
    login: BrowserLogin = Depends(get_browser_login),
):
    return {
        "authenticated": store.is_authenticated(),
        "expires_at": store.expires_at,
        "seconds_left": store.seconds_left(),
        "has_refresh_token": bool(store.refresh_token),
        "has_fingerprint": bool(store.fingerprint),
        "two_factor_pending": bool(store.two_factor_session),
        **login.status(),
    }
