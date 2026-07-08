# Инвайтинг

Сервис для приглашения пользователей в Telegram-чаты и холодной отписки (outreach) с веб-панелью и синхронизацией диалогов в **VERDI Operator Inbox**.

## Что умеет

- **Инвайт** — добавление пользователей в канал/чат по `@username`.
- **Отписка (outreach)** — первое сообщение только тем, кого уже пригласили.
- **Два пула аккаунтов:** `inviter` (инвайт) и `outreach` (отписка), ротация при flood (`peer_flood`, `Too many requests`).
- **Авторизация через панель:** телефон → код → 2FA; сессии хранятся как StringSession в SQLite (не `.session` файлы).
- **Синк в инбокс:** после успешной отписки чат появляется на Render в Operator Inbox.

## Быстрый старт (Windows)

1. Зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Конфиг — скопируйте `.env.example` → `.env` и заполните:

```env
INV_APP_HOST=127.0.0.1
INV_APP_PORT=8011
INV_DATABASE_URL=sqlite+aiosqlite:///./inviting.sqlite

INV_TG_API_ID=123456
INV_TG_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Синхронизация с Operator Inbox (Render)
INV_CONNECTOR_API_URL=https://verdi-connector-api.onrender.com
INV_CONNECTOR_SYNC_SECRET=your-long-random-secret
```

3. Запуск: двойной клик `start.bat` → **http://127.0.0.1:8011**

4. Вкладка **Аккаунты** — добавьте inviter- и outreach-аккаунты (роль выбирается при создании).

## Формат базы

CSV в панели. Колонка `username` (обязательно для резолва в Telegram):

- `someuser` или `@someuser`

## Лимиты и ротация

- **Инвайт:** настраивается в панели (пауза, лимит в день); при flood переключается на следующий inviter.
- **Отписка:** до **20 DM в день на каждый outreach-аккаунт**; при `peer_flood` — ротация на следующий outreach.

## Синхронизация с Operator Inbox

После успешной отписки сервис вызывает `POST /api/integrations/inviting/outreach` на API коннектора.

- `INV_CONNECTOR_SYNC_SECRET` = `INVITE_SYNC_SECRET` на Render.
- Ручной импорт старого чата: `scripts/import_chat_to_inbox.py`
- Экспорт StringSession для Render: `scripts/export_session_b64.py`

Инбокс: https://verdi-connector-web.onrender.com/inbox

## Структура

```
инвайтинг/
├── app/
│   ├── api/routes.py          # REST + панель
│   ├── services/
│   │   ├── inviter.py         # цикл инвайта
│   │   ├── outreach.py        # цикл отписки
│   │   └── connector_sync.py  # POST в инбокс
│   └── telegram/
│       ├── auth_service.py    # phone → code → 2FA
│       └── session_pool.py    # StringSession из БД
├── scripts/
├── .env.example
└── start.bat
```

## Важно

- Инвайтеры должны иметь право добавлять участников в целевой чат/канал.
- По invite-ссылке сервис сначала вступит аккаунтами в чат, затем начнёт инвайт.
- `.env`, `inviting.sqlite` и сессии **не в git** — на новой машине авторизуйте аккаунты заново.
- Не используйте одну сессию одновременно локально и на Render.

## Мобильный Cursor

Код в GitHub: https://github.com/marketingoperam/VERDI — папка `инвайтинг/`.

С телефона можно править код через Cursor; сам сервис нужно запускать на ПК или VPS. Инбокс для ответов клиентам доступен в браузере на телефоне.

См. также: [Клонер чатов/README.md](../Клонер%20чатов/README.md)
