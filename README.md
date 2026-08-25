# rtk-vats-api

REST API поверх внутреннего API личного кабинета **Виртуальной АТС Ростелеком**
(`cloudpbx.rt.ru/webapi`). Позволяет скриптам и AI-агентам управлять телефонией:
контакты, абоненты, группы вызовов, история звонков, записи разговоров, номера и
маршрутизация, баланс — плюс прозрачный прокси на любой из ~240 эндпоинтов ВАТС.

Вход — по логину и паролю «Ростелеком Паспорта» с подтверждением кодом из SMS;
дальше сессия поддерживается автоматически. В комплекте MCP-сервер и готовый
скилл, чтобы этим мог пользоваться AI-агент (Claude Code и совместимые).

> Неофициальный проект: использует внутреннее API ЛК, которое Ростелеком может
> изменить без предупреждения. Не аффилирован с ПАО «Ростелеком».

## Как это работает

- **Вход** — логином и паролем «Ростелеком Паспорта» плюс одноразовый код из SMS
  (`POST /auth/login` → `POST /auth/code`). Дальше сервис живёт сам: JWT ~24 минуты,
  фоновый keepalive обновляет его по refresh-токену.
- Сессия хранится в `data/session.json` (права 600) и переживает рестарт сервиса.
- Доступ к этому API — по заголовку `X-API-Key` (значение в `.env`).

### Почему для входа нужен браузерный движок

У доменов, подключённых к «Ростелеком Паспорту», классический `POST /webapi/auth`
(логин + пароль + домен) не работает: собственного пароля в ВАТС у такой учётной записи
нет, сервер отвечает «Введенные учетные данные некорректны». Вход идёт по цепочке
`/webapi/sso` → Keycloak `passport.rt.ru` → SMS-код → возврат в ЛК с токенами.

Страницы Паспорта закрыты антиботом F5: обычный HTTP-клиент получает JS-челлендж вместо
формы, а `grant_type=password` (ROPC) — тот же челлендж. Поэтому шаг логина выполняет
настоящий движок (Playwright, Chromium) — **только в момент входа, секунд на тридцать**.
Вся дальнейшая работа идёт обычным httpx без браузера.

Если ставить Chromium на сервер не хочется, есть два пути:
`scripts/login_helper.py` (браузер запускается у вас на машине, токены уходят сервису)
или ручной `POST /auth/import`.

## Запуск (разработка)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium     # нужен только для /auth/login
cp .env.example .env                      # заполнить PBX_USERNAME/PBX_PASSWORD, API_KEY
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Документация OpenAPI: `http://<host>:8010/docs`

## Авторизация

```bash
KEY="X-API-Key: <ваш API_KEY>"

# 1. Логин и пароль -> на телефон владельца учётки уходит SMS
curl -X POST http://localhost:8010/auth/login -H "$KEY" \
     -H 'Content-Type: application/json' \
     -d '{"username":"lk_1234567890","password":"..."}'
# -> {"status":"code_required","hint":"Мы отправили код на номер +7 ...","seconds_to_enter_code":300}

# 2. Код из SMS
curl -X POST http://localhost:8010/auth/code -H "$KEY" \
     -H 'Content-Type: application/json' -d '{"code":"123456"}'
# -> {"status":"ok","seconds_left":1435,"has_refresh_token":true,"has_fingerprint":true}

# Состояние сессии / принудительное обновление / отмена входа
curl http://localhost:8010/auth/status -H "$KEY"
curl -X POST http://localhost:8010/auth/refresh -H "$KEY"
curl -X POST http://localhost:8010/auth/cancel  -H "$KEY"
```

Логин и пароль можно не передавать в запросе — тогда берутся `PBX_USERNAME` / `PBX_PASSWORD`
из `.env`. Вход по одноразовому коду без пароля: `{"by_code": true}`.

На ввод кода даётся `BROWSER_CODE_TTL` секунд (по умолчанию 300): всё это время открытая
страница Паспорта ждёт код. Не успели — начните с `/auth/login`.

### Вход без браузера на сервере

```bash
# на своей машине (там, где есть playwright); токены уедут на удалённый сервис
python scripts/login_helper.py --api-url http://10.10.0.187:8010 --api-key <KEY>
```

### Ручной импорт токенов (крайний случай)

DevTools (F12) → Application → Local Storage → `token`, `refreshToken`. Значение
`fingerprint` в хранилище отсутствует — взять из адресной строки SSO-редиректа
(`...&fingerprint=...`) или выполнить `getBrowserFingerprint()` в консоли ЛК.
**Без fingerprint обновление сессии работать не будет.**

```bash
curl -X POST http://localhost:8010/auth/import -H "$KEY" \
     -H 'Content-Type: application/json' \
     -d '{"token":"<JWT>","refresh_token":"<refreshToken>","fingerprint":"<fp>"}'
```

### Домены без SSO

Если у учётной записи есть собственный пароль в самой ВАТС, работает классический вход:
`POST /auth/start` (логин/пароль/домен из `.env`) → `POST /auth/complete` с кодом из SMS.

## Эндпоинты

### Удобные (типизированные)

| Метод и путь | Что делает | Эндпоинт ВАТС |
|---|---|---|
| `GET /contacts` | Группы контактов с контактами | `GET /domain/contacts` |
| `POST /contacts` | Создать контакт | `POST /domain/contacts` |
| `PUT/DELETE /contacts/{id}` | Изменить/удалить контакт | `PUT/DELETE /domain/contacts/{id}` |
| `POST /contacts/groups` | Создать группу | `POST /domain/contacts/group` |
| `PUT/DELETE /contacts/groups/{id}` | Изменить/удалить группу | `PUT/DELETE /domain/contacts/group/{id}` |
| `GET /contacts/users` | Абоненты домена (номера, PIN) | `GET /domain/contacts/users` |
| `GET/POST /users`, `PUT/DELETE /users/{id}` | Абоненты домена | `/domain/users*` |
| `GET/POST /groups`, `GET/PUT/DELETE /groups/{id}` | Группы вызовов | `/domain/groups*` |
| `GET /calls?...` | История звонков (query пробрасывается) | `GET /domain/call_history` |
| `GET /calls/stat` | Статистика звонков | `GET /domain/call_history/stat` |
| `GET /calls/{id}/protocol` | Протокол звонка | `GET /domain/call_history/{id}/protocol` |
| `GET /calls/{id}/record` | Запись разговора (audio/*) | `GET /domain/call_history/{id}/record` |
| `GET /numbers` | Номера и маршрутизация | `GET /domain/numbers` |
| `GET /balance` | Баланс лицевого счёта | `GET /domain/payments/balance` |
| `GET /settings` | Настройки домена | `GET /domain/settings` |

### Прозрачный прокси

Любой эндпоинт ВАТС доступен через `ANY /proxy/{path}` → `/webapi/{path}`
(query, тело и метод пробрасываются; бинарные ответы отдаются как есть):

```bash
curl http://localhost:8010/proxy/domain/payments/balance -H "$KEY"
curl -X POST http://localhost:8010/proxy/callcenter/reports/by_calls \
     -H "$KEY" -H 'Content-Type: application/json' -d '{"date_from":"2026-08-01"}'
```

Карта эндпоинтов ВАТС (auth, domain/*, callcenter/*, user/*, meetings, ivr …) —
в исходнике ЛК `lk_new/assets/index-*.js` (грепать `callApi("/...`).

## Тесты

```bash
.venv/bin/python -m pytest -q
```

Моки через respx, реальных запросов к ВАТС нет.

## Навык для нейросетей

### MCP-сервер (`mcp_server/`)

MCP-сервер `rtk-vats` (stdio) с типизированными инструментами `vats_*` — подключается
к любому агенту с поддержкой MCP (Kimi Code, Claude Code/Desktop, Cursor).
Ходит в этот REST API по HTTP, поэтому запускается на машине агента:

```json
{
  "mcpServers": {
    "rtk-vats": {
      "command": "/path/to/rtk-vats-api/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/rtk-vats-api",
      "env": {
        "VATS_API_URL": "http://10.10.0.187:8010",
        "VATS_API_KEY": "<тот же API_KEY>"
      }
    }
  }
}
```

Инструменты: `vats_auth_login/code/status/refresh/cancel`, `vats_contacts_*`, `vats_domain_users`,
`vats_users_list`, `vats_groups_list`, `vats_calls_history`, `vats_call_protocol`,
`vats_call_record` (скачивает в `VATS_DOWNLOAD_DIR`, по умолчанию `./downloads`),
`vats_balance`, `vats_numbers`, `vats_settings`, `vats_proxy` (любой эндпоинт ВАТС).

### SKILL.md (`skills/rtk-vats/`)

Готовый скилл для CLI-агентов (Claude Code / Kimi Code и совместимых): флоу входа
(логин/пароль → SMS), эндпоинты, правила безопасности и справочник `references/pbx-setup.md`
по настройке АТС (абоненты, группы, IVR, расписания). Установка — скопировать или сделать symlink
`skills/rtk-vats/` в каталог скиллов агента (проектный `.kimi/skills/`,
`.claude/skills/` или пользовательский).

## Деплой (Docker)

```bash
cp .env.example .env      # заполнить PBX_USERNAME/PBX_PASSWORD, API_KEY
docker compose up -d --build
docker compose logs -f
```

Образ по умолчанию включает Chromium для входа через Паспорт. Лёгкий вариант без него —
`docker build --build-arg WITH_BROWSER=0 -t rtk-vats-api:slim .`; тогда вход выполняется
снаружи (`scripts/login_helper.py`) или через `/auth/import`.

⚠️ Порт 8010 держать в локальной сети или за VPN и не публиковать в интернет:
за ним живая сессия вашей АТС. Ключ `API_KEY` — единственная защита самого сервиса.

## Безопасность

- Пароль, SMS-коды и токены не логируются; `.env` и `data/` в `.gitignore`.
- `PBX_VERIFY_SSL=false` — только для машин за корпоративным MITM-прокси
  (иначе цепочка сертификата не сходится). На сервере оставить `true`.
- Второй фактор не обходится: SMS-код вводит человек, один раз на сессию.
- Незавершённая попытка входа закрывается по таймауту — браузер не остаётся висеть.

## Если РТК поменяет API

Точка правки одна: `app/pbx_client.py` (авторизация/refresh) + соответствующий роутер
в `app/routers/`. Прокси `/proxy/*` продолжит работать, пока не изменится сама схема путей.
