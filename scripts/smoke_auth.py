#!/usr/bin/env python3
"""Живой smoke-test: полный вход в ЛК ВАТС и пара запросов к реальному API.

Запуск из корня проекта (venv активирован, заполнен .env):

    python scripts/smoke_auth.py

Сценарий:
  1. Вход через «Ростелеком Паспорт» (логин/пароль из .env) — уходит SMS.
  2. Скрипт ждёт ввод кода из SMS в консоль.
  3. Получены токены (сохранены в data/session.json).
  4. Проверки: checkAuth, абоненты домена, принудительный refresh.

Требует playwright (`playwright install chromium`). Для доменов со «своим»
паролем в самой ВАТС (без SSO) замените login.start/submit_code на
client.auth_start()/auth_complete().
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.browser_login import BrowserLogin
from app.config import get_settings
from app.pbx_client import PBXClient
from app.session_store import SessionStore


async def main() -> int:
    settings = get_settings()
    store = SessionStore(settings.data_dir)
    client = PBXClient(settings, store)
    login = BrowserLogin(settings, store)

    try:
        if store.is_authenticated():
            print(f"Сессия уже активна (осталось {store.seconds_left()} c) — логин пропускаем.")
        else:
            print("Шаг 1: логин/пароль -> ждём SMS...")
            result = await login.start(settings.pbx_username, settings.pbx_password)
            if result["status"] == "code_required":
                print(result.get("hint") or "Отправлен код")
                code = input("Шаг 2: введите код из SMS: ").strip()
                result = await login.submit_code(code)
            print(f"Токены получены, JWT действует ещё {result.get('seconds_left')} c.")

        resp = await client.request("GET", "/auth")
        print(f"checkAuth: HTTP {resp.status_code}")

        resp = await client.request("GET", "/domain/contacts/users")
        print(f"Абоненты домена: HTTP {resp.status_code}")
        print(resp.text[:1000])

        print("Проверяем refresh...")
        await client.refresh(force=True)
        print(f"Refresh OK, токен действует ещё {store.seconds_left()} c.")

        print("\nSMOKE-TEST PASSED")
        return 0
    finally:
        await client.close()
        await login.cancel()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
