"""MCP-сервер «rtk-vats» — навык для нейросетей поверх rtk-vats-api.

Транспорт: stdio. Запуск:
    python -m mcp_server.server

Переменные окружения:
    VATS_API_URL       — адрес rtk-vats-api (по умолчанию http://127.0.0.1:8010)
    VATS_API_KEY       — ключ X-API-Key
    VATS_DOWNLOAD_DIR  — куда скачивать записи разговоров (по умолчанию ./downloads)

Подключение (пример для Kimi Code / Claude Code, mcp.json):
    {
      "mcpServers": {
        "rtk-vats": {
          "command": "/path/to/rtk-vats-api/.venv/bin/python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "/path/to/rtk-vats-api",
          "env": {"VATS_API_URL": "http://10.10.0.187:8010", "VATS_API_KEY": "..."}
        }
      }
    }
"""

import os
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("VATS_API_URL", "http://127.0.0.1:8010").rstrip("/")
API_KEY = os.environ.get("VATS_API_KEY", "")
DOWNLOAD_DIR = Path(os.environ.get("VATS_DOWNLOAD_DIR", "./downloads"))

mcp = FastMCP(
    "rtk-vats",
    instructions=(
        "Управление ВАТС Ростелеком медцентра «Анкор Плюс» через сервис rtk-vats-api. "
        "Перед работой проверь сессию: vats_auth_status. Если authenticated=false — вызови "
        "vats_auth_start, попроси у пользователя код из SMS и передай его в vats_auth_complete. "
        "Дальше сессия обновляется сама."
    ),
)


async def _req(method: str, path: str, **kwargs: Any) -> Any:
    async with httpx.AsyncClient(
        base_url=API_URL,
        headers={"X-API-Key": API_KEY},
        timeout=httpx.Timeout(60.0),
    ) as http:
        resp = await http.request(method, path, **kwargs)
        if resp.status_code == 503:
            return {
                "error": "auth_required",
                "detail": "Нет сессии ВАТС: вызови vats_auth_start, спроси у пользователя код из SMS, "
                "затем vats_auth_complete(code).",
            }
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "body": resp.text[:2000]}


# --- авторизация ---


@mcp.tool()
async def vats_auth_status() -> Any:
    """Статус сессии ВАТС: authenticated, остаток времени JWT, ожидает ли 2FA."""
    return await _req("GET", "/auth/status")


@mcp.tool()
async def vats_auth_login(username: str = "", password: str = "", by_code: bool = False) -> Any:
    """ОСНОВНОЙ вход, шаг 1: логин и пароль «Ростелеком Паспорта».

    На телефон владельца учётной записи придёт SMS с одноразовым кодом; ответ
    status='code_required' и подсказка с маскированным номером. Затем вызвать
    vats_auth_code с кодом, который назовёт пользователь.

    Пустые username/password означают «взять из конфигурации сервиса (.env)».
    by_code=True — вход по одноразовому коду без пароля.
    Учётные данные спрашивать у пользователя; не выдумывать и не подбирать."""
    payload: dict[str, Any] = {"by_code": by_code}
    if username:
        payload["username"] = username
    if password:
        payload["password"] = password
    return await _req("POST", "/auth/login", json=payload)


@mcp.tool()
async def vats_auth_code(code: str) -> Any:
    """Вход, шаг 2: одноразовый код из SMS. После успеха сессия живёт сама (авто-refresh).

    Код запрашивать у пользователя. НИКОГДА не подставлять произвольные цифры:
    неверный код тратит попытку, а новая SMS приходит с задержкой."""
    return await _req("POST", "/auth/code", json={"code": code})


@mcp.tool()
async def vats_auth_cancel() -> Any:
    """Закрыть незавершённую попытку входа (SMS не пришла / передумали)."""
    return await _req("POST", "/auth/cancel")


@mcp.tool()
async def vats_auth_refresh() -> Any:
    """Обновить JWT прямо сейчас (проверка, что refresh_token и fingerprint живы)."""
    return await _req("POST", "/auth/refresh")


@mcp.tool()
async def vats_auth_start() -> Any:
    """Классический вход (только для доменов с собственным паролем ВАТС, без SSO).

    Для доменов «Ростелеком Паспорта» вернёт «Введенные учетные данные некорректны» —
    там нужен vats_auth_login."""
    return await _req("POST", "/auth/start")


@mcp.tool()
async def vats_auth_complete(code: str) -> Any:
    """Классический вход, шаг 2: код из SMS."""
    return await _req("POST", "/auth/complete", json={"code": code})


@mcp.tool()
async def vats_auth_import(token: str, refresh_token: str = "", fingerprint: str = "") -> Any:
    """Импорт токенов из браузера (обход SSO): значения ключей token, refreshToken
    и fingerprint из localStorage ЛК ВАТС (DevTools → Application → Local Storage).
    fingerprint обязателен для работы авто-refresh — refresh_token к нему привязан."""
    return await _req(
        "POST",
        "/auth/import",
        json={"token": token, "refresh_token": refresh_token, "fingerprint": fingerprint},
    )


# --- контакты ---


@mcp.tool()
async def vats_contacts_list() -> Any:
    """Список групп контактов домена вместе с контактами."""
    return await _req("GET", "/contacts")


@mcp.tool()
async def vats_contact_add(name: str, number: str, contact_type: str = "mobile", group_id: Optional[int] = None) -> Any:
    """Добавить контакт в адресную книгу домена. contact_type: mobile/work/home/fax."""
    payload: dict[str, Any] = {"name": name, "numbers": [{"number": number, "contactType": contact_type}]}
    if group_id is not None:
        payload["groupId"] = group_id
    return await _req("POST", "/contacts", json=payload)


@mcp.tool()
async def vats_contact_update(contact_id: int, name: Optional[str] = None, group_id: Optional[int] = None) -> Any:
    """Изменить контакт (имя и/или группу)."""
    payload = {k: v for k, v in {"name": name, "groupId": group_id}.items() if v is not None}
    return await _req("PUT", f"/contacts/{contact_id}", json=payload)


@mcp.tool()
async def vats_contact_delete(contact_id: int) -> Any:
    """Удалить контакт."""
    return await _req("DELETE", f"/contacts/{contact_id}")


@mcp.tool()
async def vats_contact_group_add(name: str) -> Any:
    """Создать группу контактов."""
    return await _req("POST", "/contacts/groups", json={"name": name})


@mcp.tool()
async def vats_contact_group_delete(group_id: int) -> Any:
    """Удалить группу контактов."""
    return await _req("DELETE", f"/contacts/groups/{group_id}")


@mcp.tool()
async def vats_domain_users() -> Any:
    """Абоненты домена ВАТС: внутренние пользователи с номерами и PIN."""
    return await _req("GET", "/contacts/users")


# --- абоненты и группы вызовов ---


@mcp.tool()
async def vats_users_list() -> Any:
    """Пользователи домена (учётные записи абонентов)."""
    return await _req("GET", "/users")


@mcp.tool()
async def vats_groups_list() -> Any:
    """Группы обработки вызовов."""
    return await _req("GET", "/groups")


# --- звонки ---


@mcp.tool()
async def vats_calls_history(date_from: Optional[str] = None, date_to: Optional[str] = None) -> Any:
    """История звонков домена. Даты в формате ГГГГ-ММ-ДД."""
    params = {k: v for k, v in {"date_from": date_from, "date_to": date_to}.items() if v}
    return await _req("GET", "/calls", params=params)


@mcp.tool()
async def vats_call_protocol(call_id: str) -> Any:
    """Поэтапный протокол звонка (маршрутизация, плечи, участники)."""
    return await _req("GET", f"/calls/{call_id}/protocol")


@mcp.tool()
async def vats_call_record(call_id: str) -> Any:
    """Скачать запись разговора. Возвращает путь к сохранённому аудиофайлу."""
    async with httpx.AsyncClient(
        base_url=API_URL,
        headers={"X-API-Key": API_KEY},
        timeout=httpx.Timeout(120.0),
    ) as http:
        resp = await http.get(f"/calls/{call_id}/record")
        if resp.status_code != 200:
            return {"error": resp.status_code, "body": resp.text[:1000]}
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ext = ".wav" if "wav" in resp.headers.get("content-type", "") else ".bin"
        path = DOWNLOAD_DIR / f"call_{call_id}{ext}"
        path.write_bytes(resp.content)
        return {"saved_to": str(path.resolve()), "bytes": len(resp.content)}


# --- домен ---


@mcp.tool()
async def vats_balance() -> Any:
    """Баланс лицевого счёта ВАТС."""
    return await _req("GET", "/balance")


@mcp.tool()
async def vats_numbers() -> Any:
    """Номера домена и правила маршрутизации."""
    return await _req("GET", "/numbers")


@mcp.tool()
async def vats_settings() -> Any:
    """Настройки домена."""
    return await _req("GET", "/settings")


# --- универсальный доступ ---


@mcp.tool()
async def vats_proxy(
    method: str,
    path: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
) -> Any:
    """Запрос к любому эндпоинту ВАТС через прокси (для операций, которым нет отдельного инструмента).
    path — путь после /webapi, например "domain/ivr_scenarios" или "callcenter/reports/by_calls"."""
    return await _req(method.upper(), f"/proxy/{path.lstrip('/')}", params=params, json=body)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
