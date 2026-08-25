"""Фоновый keepalive сессии ВАТС.

JWT живёт ~24 минуты, а срок жизни refresh_token ограничен (по наблюдениям —
часы). Поэтому токен обновляем заблаговременно и регулярно: пока сервис
запущен, сессия живёт без ручного логина. Если refresh не удался (сессия
протухла окончательно) — ждём повторного импорта токенов через /auth/import.
"""

import asyncio
import logging

from .pbx_client import PBXAuthRequired, PBXClient

log = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # как часто проверяем сессию
REFRESH_MARGIN = 300  # обновляем, если JWT живёт меньше этого
FAIL_BACKOFF = 300  # пауза после неуспешного refresh


async def keepalive_loop(client: PBXClient) -> None:
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            store = client.store
            left = store.seconds_left()
            if store.refresh_token and (left is None or left < REFRESH_MARGIN):
                log.info("keepalive: обновляю токен ВАТС (осталось %s с)", left)
                await client.refresh(force=True)
        except PBXAuthRequired:
            log.warning(
                "keepalive: refresh-токен недействителен — нужен повторный логин "
                "(/auth/start + SMS или /auth/import из браузера)"
            )
            await asyncio.sleep(FAIL_BACKOFF)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("keepalive: ошибка при обновлении токена")
            await asyncio.sleep(FAIL_BACKOFF)
