"""Вход в ЛК ВАТС через «Ростелеком Паспорт» (SSO) реальным браузерным движком.

Зачем браузер. У доменов, подключённых к Ростелеком Паспорту, классический
`POST /webapi/auth` (логин+пароль+домен) не работает: сервер отвечает
«Введенные учетные данные некорректны» — пароля в самой ВАТС у такой учётки нет.
Вход идёт по цепочке:

    /webapi/sso?redirect_uri=…&auth_when_one=1
      -> passport.rt.ru/auth/realms/b2b/... (Keycloak: #username + #password)
      -> экран одноразового кода из SMS (#rt-code-0 … #rt-code-5)
      -> обратно на /webapi/sso?...&fingerprint=…
      -> lk_new кладёт token / refreshToken в localStorage

Страницы Паспорта закрыты антиботом F5 (куки TS*), поэтому воспроизвести цепочку
голым httpx нельзя — нужен настоящий движок. Playwright ставится опционально:
модуль импортируется лениво, и сервис работает без него (режим /auth/import).

Двухшаговость (пароль -> SMS) требует, чтобы браузер ЖИЛ между запросами:
`start()` останавливается на экране кода и держит страницу открытой,
`submit_code()` дозаполняет её. Незавершённая сессия закрывается по TTL.
"""

import asyncio
import logging
import re
import time
from typing import Any, Optional

from .config import Settings
from .session_store import SessionStore

log = logging.getLogger(__name__)

LK_LOGIN_URL = "/lk_new/#/login"
# точка входа SSO; ЛК подставляет сюда свой отпечаток браузера — к нему привяжется refresh_token
SSO_ENTRY_TMPL = "{base}/webapi/sso?redirect_uri={redirect}&auth_when_one=1&fingerprint={fp}"
SSO_REDIRECT = "https%3A%2F%2Fp2.cloudpbx.rt.ru%2Flk_new%2F%23%2Flogin%2Fsso"
COOKIE_ACCEPT = "text=Принять"

USERNAME_SEL = "#username"
PASSWORD_SEL = "#password"
LOGIN_BTN_SEL = "#kc-login"
OTP_LOGIN_BTN_SEL = "#otp_login_btn"
CODE_CELL_SEL = "#rt-code-0"
CODE_HIDDEN_SEL = "#rt-code-input"
KC_ERROR_SEL = "#input-error, .rt-input-container__meta--error, .pf-c-alert__title"

_FINGERPRINT_RE = re.compile(r"[?&]fingerprint=([0-9a-f]{16,64})")
_TOKEN_WAIT_TIMEOUT = 60  # сколько ждём появления токена в localStorage после успеха


class BrowserLoginError(Exception):
    """Ошибка браузерного входа (передаётся наверх как 400/502)."""


class BrowserLoginUnavailable(BrowserLoginError):
    """Playwright не установлен или не скачан браузер."""


class BrowserLogin:
    """Пошаговый SSO-вход. Один экземпляр на сервис, шаги под общим lock."""

    def __init__(self, settings: Settings, store: SessionStore):
        self.settings = settings
        self.store = store
        self._lock = asyncio.Lock()
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._nav_urls: list[str] = []
        self._pending_until: float = 0.0
        self._code_hint: Optional[str] = None
        self._fingerprint: str = ""

    # --- состояние ---

    @property
    def code_pending(self) -> bool:
        return self._page is not None and time.time() < self._pending_until

    def status(self) -> dict[str, Any]:
        return {
            "code_pending": self.code_pending,
            "seconds_to_enter_code": max(0, int(self._pending_until - time.time())) if self.code_pending else 0,
            "code_hint": self._code_hint if self.code_pending else None,
        }

    # --- служебное ---

    async def _launch(self) -> Any:
        try:
            from playwright.async_api import async_playwright  # ленивый импорт
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise BrowserLoginUnavailable(
                "Не установлен playwright. Установите: pip install playwright && playwright install chromium "
                "(или используйте /auth/import с токенами из браузера)"
            ) from exc

        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=self.settings.browser_headless)
        except Exception as exc:  # pragma: no cover
            await self._cleanup()
            raise BrowserLoginUnavailable(
                f"Не удалось запустить Chromium ({exc}). Выполните: playwright install chromium"
            ) from exc

        ctx = await self._browser.new_context(
            ignore_https_errors=not self.settings.pbx_verify_ssl,
            locale="ru-RU",
            user_agent=self.settings.browser_user_agent or None,
        )
        page = await ctx.new_page()
        self._nav_urls = []
        page.on(
            "framenavigated",
            lambda f: self._nav_urls.append(f.url) if f == page.main_frame else None,
        )
        return page

    async def _cleanup(self) -> None:
        for closer in (
            getattr(self._browser, "close", None),
            getattr(self._pw, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:  # pragma: no cover
                log.debug("browser-login: ошибка при закрытии", exc_info=True)
        self._pw = self._browser = self._page = None
        self._pending_until = 0.0
        self._code_hint = None
        self._fingerprint = ""

    async def _dismiss_cookies(self, page: Any) -> None:
        try:
            await page.click(COOKIE_ACCEPT, timeout=3000)
        except Exception:
            pass  # баннера может не быть — это норма

    async def _page_error(self, page: Any) -> Optional[str]:
        try:
            el = await page.query_selector(KC_ERROR_SEL)
            if el:
                text = (await el.inner_text()).strip()
                return text[:200] or None
        except Exception:  # pragma: no cover
            pass
        return None

    def _fingerprint_from_nav(self) -> str:
        """Отпечаток, к которому привязан refresh_token: наш посчитанный либо из URL."""
        if self._fingerprint:
            return self._fingerprint
        for url in reversed(self._nav_urls):
            m = _FINGERPRINT_RE.search(url)
            if m:
                return m.group(1)
        return ""

    async def _harvest_tokens(self, page: Any) -> dict[str, Any]:
        """Ждём, пока ЛК положит токены в localStorage, и сохраняем сессию."""
        deadline = time.time() + _TOKEN_WAIT_TIMEOUT
        data: dict[str, str] = {}
        while time.time() < deadline:
            try:
                data = await page.evaluate(
                    "() => ({token: localStorage.getItem('token') || '',"
                    " refreshToken: localStorage.getItem('refreshToken') || ''})"
                )
            except Exception:  # страница в этот момент может редиректиться
                data = {}
            if data.get("token"):
                break
            await asyncio.sleep(1)

        token = (data or {}).get("token", "")
        if not token:
            raise BrowserLoginError(
                "Вход прошёл, но ЛК не положил token в localStorage — "
                "возможно, изменился фронтенд ЛК или домен заблокирован"
            )

        fingerprint = self._fingerprint_from_nav()
        if not fingerprint:
            # запасной путь: посчитать отпечаток тем же кодом, что и сам ЛК
            try:
                fingerprint = await page.evaluate(
                    "async () => (typeof getBrowserFingerprint === 'function')"
                    " ? getBrowserFingerprint() : ''"
                )
            except Exception:  # pragma: no cover
                fingerprint = ""
        if not fingerprint:
            log.warning("browser-login: fingerprint не найден — refresh_token может не работать")

        self.store.save_tokens(token, (data or {}).get("refreshToken", ""), fingerprint)
        log.info("browser-login: сессия получена (exp=%s, fingerprint=%s)", self.store.expires_at, bool(fingerprint))
        return {
            "status": "ok",
            "expires_at": self.store.expires_at,
            "seconds_left": self.store.seconds_left(),
            "has_refresh_token": bool(self.store.refresh_token),
            "has_fingerprint": bool(fingerprint),
        }

    # --- шаги входа ---

    async def start(self, username: str, password: str = "", by_code: bool = False) -> dict[str, Any]:
        """Шаг 1: открыть ЛК, уйти в Паспорт, отправить логин/пароль.

        by_code=True — вход «по временному коду» без пароля (кнопка Паспорта).
        Возвращает status='code_required' (пришла SMS) либо 'ok' (2FA не спросили).
        """
        async with self._lock:
            await self._cleanup()  # не тащим прошлую незавершённую попытку
            page = await self._launch()
            self._page = page
            base = self.settings.pbx_base_url.rstrip("/")
            try:
                # 1. страница ЛК: там живёт та же функция отпечатка, что использует фронт
                await page.goto(base + LK_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                await self._dismiss_cookies(page)
                self._fingerprint = await self._browser_fingerprint(page)

                # 2. точка входа SSO с этим отпечатком -> редирект на Ростелеком Паспорт
                await page.goto(
                    SSO_ENTRY_TMPL.format(base=base, redirect=SSO_REDIRECT, fp=self._fingerprint),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.wait_for_selector(USERNAME_SEL, timeout=45000)
                await self._dismiss_cookies(page)

                await page.fill(USERNAME_SEL, username)
                if by_code:
                    await page.click(OTP_LOGIN_BTN_SEL)
                else:
                    if not password:
                        raise BrowserLoginError("Не передан пароль (или используйте by_code=true)")
                    await page.fill(PASSWORD_SEL, password)
                    await page.click(LOGIN_BTN_SEL)

                # дальше либо экран кода, либо сразу возврат в ЛК
                for _ in range(int(self.settings.browser_step_timeout)):
                    if await page.query_selector(CODE_CELL_SEL):
                        self._pending_until = time.time() + self.settings.browser_code_ttl
                        self._code_hint = await self._code_screen_hint(page)
                        log.info("browser-login: запрошен код из SMS (%s)", self._code_hint)
                        return {
                            "status": "code_required",
                            "hint": self._code_hint,
                            "seconds_to_enter_code": int(self.settings.browser_code_ttl),
                        }
                    if "/lk_new/" in page.url and "passport.rt.ru" not in page.url:
                        result = await self._harvest_tokens(page)
                        await self._cleanup()
                        return result
                    err = await self._page_error(page)
                    if err:
                        await self._cleanup()
                        raise BrowserLoginError(f"Паспорт отклонил вход: {err}")
                    await asyncio.sleep(1)

                await self._cleanup()
                raise BrowserLoginError("Истекло ожидание ответа Паспорта (ни код, ни возврат в ЛК)")
            except BrowserLoginError:
                raise
            except Exception as exc:
                await self._cleanup()
                raise BrowserLoginError(f"Сбой браузерного входа: {exc}") from exc

    async def _browser_fingerprint(self, page: Any) -> str:
        """Отпечаток браузера кодом самого ЛК (helper.fp.js): getBrowserFingerprint()."""
        for _ in range(10):
            try:
                fp = await page.evaluate(
                    "() => (typeof window.getBrowserFingerprint === 'function')"
                    " ? window.getBrowserFingerprint() : ''"
                )
            except Exception:  # pragma: no cover - страница ещё грузится
                fp = ""
            if fp:
                return fp
            await asyncio.sleep(1)
        raise BrowserLoginError(
            "Не удалось вычислить fingerprint на странице ЛК (getBrowserFingerprint недоступна)"
        )

    async def _code_screen_hint(self, page: Any) -> Optional[str]:
        """Строка вида «Мы отправили код на номер +7 914 …» — показать пользователю."""
        try:
            text = await page.inner_text("body")
        except Exception:  # pragma: no cover
            return None
        for line in text.splitlines():
            line = line.strip()
            if "код" in line.lower() and any(ch.isdigit() for ch in line):
                return line[:120]
        return None

    async def submit_code(self, code: str) -> dict[str, Any]:
        """Шаг 2: ввести код из SMS на открытой странице Паспорта."""
        async with self._lock:
            if self._page is None:
                raise BrowserLoginError("Нет активной попытки входа — начните с /auth/login")
            if time.time() >= self._pending_until:
                await self._cleanup()
                raise BrowserLoginError("Код просрочен, SMS-сессия закрыта — начните вход заново")

            digits = "".join(ch for ch in code if ch.isdigit())
            if not digits:
                raise BrowserLoginError("Код должен состоять из цифр")

            page = self._page
            try:
                # Визуальные ячейки #rt-code-0..5 — это оформление; реальный ввод идёт
                # в #rt-code-input поверх них (он перехватывает клики). Печатаем туда,
                # форма сабмитится сама при шестой цифре.
                await page.click(CODE_HIDDEN_SEL, timeout=15000)
                await page.keyboard.type(digits, delay=80)
                if len(digits) < 6:
                    await page.keyboard.press("Enter")

                for _ in range(int(self.settings.browser_step_timeout)):
                    if "/lk_new/" in page.url and "passport.rt.ru" not in page.url:
                        result = await self._harvest_tokens(page)
                        await self._cleanup()
                        return result
                    err = await self._page_error(page)
                    if err:
                        raise BrowserLoginError(f"Паспорт не принял код: {err}")
                    await asyncio.sleep(1)

                raise BrowserLoginError("Код отправлен, но ЛК не открылся — попробуйте войти заново")
            except BrowserLoginError:
                raise
            except Exception as exc:
                # Страницу НЕ закрываем: код из той же SMS ещё действителен,
                # пользователь может повторить попытку (иначе сгорит лишняя SMS).
                # Незавершённая сессия всё равно закроется по TTL.
                raise BrowserLoginError(f"Сбой при вводе кода: {exc}") from exc

    async def cancel(self) -> dict[str, Any]:
        """Закрыть незавершённую попытку входа (браузер)."""
        async with self._lock:
            await self._cleanup()
            return {"status": "cancelled"}
