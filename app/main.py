"""rtk-vats-api — REST API поверх ЛК ВАТС Ростелеком для медцентра «Анкор Плюс»."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from . import deps
from .config import get_settings
from .deps import require_api_key
from .keepalive import keepalive_loop
from .routers import auth, calls, contacts, domain, proxy, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # тот же singleton, что используют роутеры через DI
    client = deps.get_pbx_client(settings, deps.get_store(settings))
    keepalive = asyncio.create_task(keepalive_loop(client))
    yield
    keepalive.cancel()
    await client.close()
    browser_login = deps.current_browser_login()
    if browser_login is not None:
        await browser_login.cancel()  # незавершённый вход не должен пережить сервис


app = FastAPI(
    title="rtk-vats-api",
    description="API-обёртка над внутренним API ЛК ВАТС Ростелеком (cloudpbx.rt.ru). "
    "Авторизация: заголовок X-API-Key. Управление сессией ВАТС: /auth/*.",
    version="0.1.0",
    lifespan=lifespan,
)

for r in (auth.router, contacts.router, users.router, calls.router, domain.router, proxy.router):
    app.include_router(r, dependencies=[Depends(require_api_key)])


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
