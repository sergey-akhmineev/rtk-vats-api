"""Помощник входа: браузер запускается ЛОКАЛЬНО, сервис остаётся без Chromium.

Зачем. Вход в ЛК ВАТС у SSO-доменов проходит только через «Ростелеком Паспорт»,
чьи страницы закрыты антиботом F5 — нужен настоящий движок JS. Если ставить
Chromium на сервер не хочется (headless-хост, тонкий контейнер), запустите этот
скрипт на своей машине: он проведёт логин + SMS и отправит готовые токены
на удалённый сервис через POST /auth/import.

Примеры:
    # сервис локально, креды из .env
    python scripts/login_helper.py

    # сервис на другом хосте
    python scripts/login_helper.py --api-url http://10.10.0.187:8010 --api-key <KEY>

    # показать окно браузера (отладка)
    python scripts/login_helper.py --headed
"""

import argparse
import asyncio
import getpass
import sys
import tempfile

import httpx
from dotenv import dotenv_values

sys.path.insert(0, ".")

from app.browser_login import BrowserLogin, BrowserLoginError  # noqa: E402
from app.config import Settings  # noqa: E402
from app.session_store import SessionStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    env = dotenv_values(".env")
    p = argparse.ArgumentParser(description="Вход в ЛК ВАТС и передача токенов сервису rtk-vats-api")
    p.add_argument("--api-url", default="http://127.0.0.1:8010", help="адрес сервиса rtk-vats-api")
    p.add_argument("--api-key", default=env.get("API_KEY", ""), help="X-API-Key сервиса")
    p.add_argument("--username", default=env.get("PBX_USERNAME", ""), help="логин Ростелеком Паспорта")
    p.add_argument("--password", default=env.get("PBX_PASSWORD", ""), help="пароль (спросим, если не задан)")
    p.add_argument("--base-url", default=env.get("PBX_BASE_URL", "https://p2.cloudpbx.rt.ru"))
    p.add_argument("--by-code", action="store_true", help="вход по одноразовому коду, без пароля")
    p.add_argument("--headed", action="store_true", help="показать окно браузера")
    p.add_argument("--insecure", action="store_true", help="не проверять TLS-сертификат ВАТС")
    return p.parse_args()


async def main() -> int:
    args = parse_args()
    username = args.username or input("Логин Ростелеком Паспорта: ").strip()
    password = "" if args.by_code else (args.password or getpass.getpass("Пароль: "))

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            pbx_base_url=args.base_url,
            pbx_verify_ssl=not args.insecure,
            browser_headless=not args.headed,
            data_dir=tmp,
        )
        store = SessionStore(tmp)
        login = BrowserLogin(settings, store)

        try:
            result = await login.start(username=username, password=password, by_code=args.by_code)
            if result.get("status") == "code_required":
                print(result.get("hint") or "Отправлен одноразовый код")
                code = input("Код из SMS: ").strip()
                result = await login.submit_code(code)
        except BrowserLoginError as exc:
            print(f"Не удалось войти: {exc}", file=sys.stderr)
            await login.cancel()
            return 1

        print(f"Вход выполнен, JWT живёт {result.get('seconds_left')} с. Передаю токены сервису…")
        resp = httpx.post(
            args.api_url.rstrip("/") + "/auth/import",
            headers={"X-API-Key": args.api_key},
            json={
                "token": store.token or "",
                "refresh_token": store.refresh_token or "",
                "fingerprint": store.fingerprint or "",
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"Сервис отклонил токены: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
            return 1
        print("Готово:", resp.json())
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
