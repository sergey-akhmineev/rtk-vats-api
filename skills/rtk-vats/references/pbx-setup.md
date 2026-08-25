# ВАТС Ростелеком — карта API и настройка АТС (справочник к навыку rtk-vats)

Схемы внутреннего API ЛК публично не документированы. Всё ниже получено из JS-бандла
личного кабинета и проверено на живой установке. При расхождении верить бандлу.

## Как найти эндпоинт, которого здесь нет

Бандл ЛК: `https://<хост ВАТС>/lk_new/assets/index-*.js`.

```bash
curl -sk "https://<хост>/lk_new/assets/index-XXXX.js" -o /tmp/lk.js
grep -o 'callApi("[^"]*"' /tmp/lk.js | sort -u | less
```

Затем вызывать через прокси сервиса: `ANY /proxy/<путь после /webapi>`.

## Удобные роуты сервиса → эндпоинты ВАТС

| Роут rtk-vats-api | ВАТС |
|---|---|
| `GET /contacts` | `GET /domain/contacts` |
| `POST /contacts`, `PUT/DELETE /contacts/{id}` | `/domain/contacts[/{id}]` |
| `POST /contacts/groups`, `PUT/DELETE /contacts/groups/{id}` | `/domain/contacts/group[/{id}]` |
| `GET /contacts/users` | `GET /domain/contacts/users` |
| `GET/POST /users`, `PUT/DELETE /users/{id}` | `/domain/users[/{id}]` |
| `GET/POST /groups`, `GET/PUT/DELETE /groups/{id}` | `/domain/groups[/{id}]` |
| `GET /calls`, `/calls/stat` | `/domain/call_history[/stat]` |
| `GET /calls/{id}/protocol`, `/record` | `/domain/call_history/{id}/{protocol,record}` |
| `GET /numbers` | `GET /domain/numbers` |
| `GET /balance` | `GET /domain/payments/balance` |
| `GET /settings` | `GET /domain/settings` |
| — | `GET /domain/settings/nextpin` — следующий свободный PIN абонента |
| — | `POST /domain/payments/promised_payment` — обещанный платёж (только по команде пользователя) |

## Модели (из бандла ЛК)

**Абонент** (`addUser`): `name`, `displayName`, `pin`, `password` + `passwordConfirm`,
`email`, `phoneNumber`, `recording`, `voicemailEnabled`, … PIN брать из
`/domain/settings/nextpin`, а не угадывать.

**Правило маршрутизации номера**: `{action, actionParam, priority, schedule: {id, name, workHours}}`.
Действия: `user`, `group`, `ivr`, `reject`, `uservm`, `groupvm`, `fax*`.
`actionParam` — id абонента/группы/IVR в зависимости от `action`.

**Кнопка IVR**: `{key, action, actionParam, actionParamFile}`.
Действия IVR по id: `1` = группа, `2` = абонент, `4` = внешний номер, `7` = фраза,
`8` = отбой, `9` = повтор меню, `10` = донабор. Остальные id (3, 5, 6, 11–13) в бандле
присутствуют, назначение не проверялось.

**Голосовые файлы**: WAV 8 кГц. Эндпоинт загрузки медиа в `/webapi` найти не удалось —
файлы загружаются вручную через веб-интерфейс ЛК. Сгенерировать приветствие можно, например,
через piper: `piper -m ru_RU-irina-medium.onnx -f greeting.wav` + `ffmpeg -ar 8000`.

## Типовой порядок настройки входящей линии

1. Проверить баланс: при долге домен блокируется и любые POST отбиваются.
2. Завести абонентов (`POST /users`), PIN — из `nextpin`.
3. Собрать группу обработки вызовов (`POST /groups`) из этих абонентов.
4. Загрузить голосовые файлы через ЛК, собрать IVR-меню.
5. Повесить правила на номер (`GET /numbers` → id номера) с расписанием: в рабочие часы → IVR
   или группа, вне их → фраза/голосовая почта.
6. SIP-аккаунты абонентов раздать на телефоны (у Yealink — автопровижининг: файл `<mac>.cfg`
   на HTTP-сервере + DHCP option 66).

## Способы авторизации: что когда применять

| Способ | Когда | Требует |
|---|---|---|
| `/auth/login` + `/auth/code` | домен подключён к «Ростелеком Паспорту» (обычный случай) | playwright на сервере |
| `scripts/login_helper.py` | сервер без браузера: вход с машины пользователя, токены уходят сервису | playwright у пользователя |
| `/auth/start` + `/auth/complete` | у учётной записи есть собственный пароль в самой ВАТС | — |
| `/auth/import` | всё остальное сломалось: перенос токенов из браузера руками | — |

Ручной импорт: DevTools (F12) → Application → Local Storage → ключи `token` и `refreshToken`.
**`fingerprint` в хранилище отсутствует** — его вычисляет фронтенд; взять из адресной строки
SSO-редиректа (`…&fingerprint=…`) либо в консоли ЛК: `getBrowserFingerprint()`.
Без fingerprint обновление сессии не работает: `POST /webapi/auth/refresh_token` требует пару
`refresh_token` + `fingerprint` («Invalid token» без него, «Token not found or expired» с чужим).

## Ограничения, о которых стоит знать заранее

- Страницы «Ростелеком Паспорта» закрыты антиботом F5 (куки `TS*`): обычный HTTP-клиент
  получает JS-челлендж вместо формы логина, а `grant_type=password` (ROPC) отвечает тем же
  челленджем. Поэтому вход возможен только браузерным движком.
- JWT живёт ~24 минуты, refresh-токен — часы. Пока сервис запущен, keepalive обновляет
  сессию сам; после долгого простоя нужен повторный вход.
- У РТК есть отдельный **интеграционный API** (`X-Client-ID` + подпись sha256): webhooks
  звонков, call_back, доступ к записям **без сессии ЛК**. Включается услугой в ЛК, возможно
  платная. Для постоянной автоматизации это более правильный путь, чем сессия ЛК.
