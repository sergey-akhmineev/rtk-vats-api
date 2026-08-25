"""Клиент к внутреннему API ЛК ВАТС Ростелеком (https://p2.cloudpbx.rt.ru/webapi).

Авторизация: POST /webapi/auth (form-urlencoded).
  Шаг 1: username+password+domain -> в ответе two_factor + hash (сессия 2FA), SMS на телефон.
  Шаг 2: + two_factor_session=hash, two_factor_code=<код из SMS> -> JWT + refresh_token.
JWT живёт ~24 минуты; обновление: POST /webapi/auth/refresh_token (form: refresh_token).
"""

import asyncio
import logging
from typing import Any, Optional

import httpx

from .config import Settings
from .session_store import SessionStore

log = logging.getLogger(__name__)


class PBXError(Exception):
    """Ошибка вызова API ВАТС."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"PBX {status_code}: {detail}")


class PBXAuthRequired(PBXError):
    """Нет валидной сессии: нужен повторный логин с SMS-кодом."""

    def __init__(self, detail: str = "Требуется авторизация: /auth/start, затем /auth/complete с SMS-кодом"):
        super().__init__(503, detail)


class PBXClient:
    def __init__(self, settings: Settings, store: SessionStore):
        self.settings = settings
        self.store = store
        self._refresh_lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            if not self.settings.pbx_verify_ssl:
                log.warning("PBX_VERIFY_SSL=false: проверка TLS-сертификата ВАТС отключена")
            self._client = httpx.AsyncClient(
                base_url=self.settings.webapi_url,
                verify=self.settings.pbx_verify_ssl,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json()
        except Exception:
            raise PBXError(resp.status_code, resp.text[:500])
        # часть ответов завёрнута в {"data": {...}}, часть отдаёт объект напрямую
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            return body["data"]
        return body if isinstance(body, dict) else {"data": body}

    def _login_form(self) -> dict[str, str]:
        return {
            "username": self.settings.pbx_username,
            "password": self.settings.pbx_password,
            "domain": self.settings.pbx_domain,
        }

    def _apply_auth_response(self, data: dict[str, Any]) -> str:
        """Разбор ответа /auth. Возвращает статус: 'ok' или 'sms_required'."""
        token = data.get("token")
        refresh_token = data.get("refresh_token") or data.get("refreshToken")
        if token:
            self.store.save_tokens(token, refresh_token or "")
            log.info("ВАТС: получен JWT (exp=%s)", self.store.expires_at)
            return "ok"
        # 2FA: сервер вернул two_factor + hash (или two_factor_session)
        two_factor = data.get("two_factor") or data.get("twoFactor")
        session = data.get("hash") or data.get("two_factor_session")
        if two_factor or session:
            if not session:
                raise PBXError(502, f"2FA включена, но сессия 2FA не найдена в ответе: {list(data)}")
            self.store.save_two_factor_session(str(session))
            log.info("ВАТС: запрошен SMS-код (two_factor_session сохранена)")
            return "sms_required"
        raise PBXError(502, f"Неожиданный ответ /auth: {list(data)}")

    async def auth_start(self) -> dict[str, Any]:
        """Шаг 1: логин/пароль. Отправляет SMS и сохраняет two_factor_session."""
        http = await self._http()
        resp = await http.post("/auth", data=self._login_form())
        if resp.status_code != 200:
            raise PBXError(resp.status_code, resp.text[:500])
        status = self._apply_auth_response(self._unwrap(resp))
        if status == "ok":
            return {"status": "ok", "expires_at": self.store.expires_at}
        return {"status": "sms_required"}

    def import_tokens(self, token: str, refresh_token: str = "", fingerprint: str = "") -> dict[str, Any]:
        """Импорт токенов из браузера (обход SSO-логина): валидация и сохранение."""
        token = token.strip()
        if token.count(".") != 2:
            raise PBXError(400, "Это не JWT — скопируйте значение ключа token из localStorage целиком")
        self.store.save_tokens(token, refresh_token.strip(), fingerprint.strip())
        if not self.store.expires_at:
            raise PBXError(400, "Не удалось разобрать exp из JWT")
        log.info("ВАТС: токены импортированы (exp=%s)", self.store.expires_at)
        return {
            "status": "ok",
            "expires_at": self.store.expires_at,
            "seconds_left": self.store.seconds_left(),
            "has_refresh_token": bool(self.store.refresh_token),
        }

    async def auth_complete(self, code: str) -> dict[str, Any]:
        """Шаг 2: SMS-код. Возвращает токены."""
        session = self.store.two_factor_session
        if not session:
            raise PBXAuthRequired("Нет активной 2FA-сессии — сначала вызовите /auth/start")
        http = await self._http()
        form = self._login_form()
        form["two_factor_session"] = session
        form["two_factor_code"] = code
        resp = await http.post("/auth", data=form)
        if resp.status_code != 200:
            raise PBXError(resp.status_code, resp.text[:500])
        status = self._apply_auth_response(self._unwrap(resp))
        if status != "ok":
            raise PBXError(502, "После SMS-кода токен не получен (повторите /auth/start)")
        return {"status": "ok", "expires_at": self.store.expires_at}

    async def refresh(self, force: bool = False) -> None:
        """Обновление JWT по refresh_token. Под lock — без параллельных refresh.

        force=True — обновить, даже если текущий JWT ещё валиден (keepalive:
        refresh_token живёт недолго, поэтому крутим его заблаговременно).
        """
        async with self._refresh_lock:
            if not force and self.store.is_authenticated():
                return  # кто-то уже обновил, пока ждали lock
            refresh_token = self.store.refresh_token
            if not refresh_token:
                raise PBXAuthRequired()
            http = await self._http()
            form = {"refresh_token": refresh_token}
            if self.store.fingerprint:
                # refresh_token привязан к fingerprint браузера, в котором был логин
                form["fingerprint"] = self.store.fingerprint
            resp = await http.post("/auth/refresh_token", data=form)
            if resp.status_code != 200:
                log.warning("ВАТС: refresh не удался (%s), нужен повторный логин", resp.status_code)
                self.store.clear()
                raise PBXAuthRequired()
            status = self._apply_auth_response(self._unwrap(resp))
            if status != "ok":
                self.store.clear()
                raise PBXAuthRequired("Refresh вернул 2FA — нужен повторный логин")
            log.info("ВАТС: токен обновлён по refresh_token")

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Any = None,
        data: Any = None,
        content: Any = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        """Запрос к /webapi/<path> с Bearer-токеном и авто-refresh."""
        if not self.store.is_authenticated():
            if self.store.refresh_token:
                await self.refresh()
            else:
                raise PBXAuthRequired()

        http = await self._http()

        async def _do() -> httpx.Response:
            hdrs = {"Authorization": f"Bearer {self.store.token}"}
            if headers:
                hdrs.update(headers)
            return await http.request(
                method,
                path,
                params=params,
                json=json_body,
                data=data,
                content=content,
                headers=hdrs,
            )

        resp = await _do()
        if resp.status_code == 401:
            await self.refresh()
            resp = await _do()
            if resp.status_code == 401:
                self.store.clear()
                raise PBXAuthRequired()
        return resp
