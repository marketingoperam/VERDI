# Клонер чатов — VERDI

Папка с инструментами для работы с Telegram-чатами в экосистеме VERDI.

## Что здесь

| Проект | Путь | Назначение |
|--------|------|------------|
| **ShadowChat** | `shadowchat/` | Зеркалирование рабочих чатов для онбординга сотрудников |
| **Operator Inbox** | `../verdi-connector/` | Веб-инбокс оператора (основная копия в корне репозитория) |
| **Инвайтинг** | `../инвайтинг/` | Панель инвайта + холодная отписка с синком в инбокс |

> Актуальный **verdi-connector** с деплоем на Render и синхронизацией отписки лежит в **`verdi-connector/`** в корне репозитория. Копия в `Клонер чатов/verdi-connector/` — устаревший дубликат, не используйте для разработки.

## GitHub

Репозиторий: **https://github.com/marketingoperam/VERDI**

```bash
git clone https://github.com/marketingoperam/VERDI.git
cd VERDI
```

## Работа через мобильный Cursor

1. Установите **Cursor** на телефон и войдите в тот же аккаунт, что на компьютере.
2. Подключите GitHub и откройте репозиторий `marketingoperam/VERDI`.
3. Редактируйте код в чате — агент видит те же файлы, что и на ПК.
4. Для задач без локального Python/Telethon используйте **Cloud Agent** (изменения уходят в ветку на GitHub).
5. На компьютере: `git pull` — и вы продолжаете с того же состояния.

### Что работает с телефона без ПК

| Сервис | URL | Комментарий |
|--------|-----|-------------|
| Operator Inbox | https://verdi-connector-web.onrender.com/inbox | Ответы операторов, синие точки на новых чатах |
| API инбокса | https://verdi-connector-api.onrender.com | Бэкенд на Render |

### Что нужно запускать на ПК (или VPS)

| Сервис | Порт | Запуск |
|--------|------|--------|
| Инвайтинг | 8011 | `инвайтинг/start.bat` → http://127.0.0.1:8011 |
| ShadowChat | 8001 | `shadowchat/start.bat` → http://127.0.0.1:8001 |

Telethon-сессии и SQLite-базы **не в git** — на новой машине создайте `.env` из `.env.example` и заново авторизуйте аккаунты через панель.

### Секреты (не коммитятся)

Скопируйте на каждой машине:

- `инвайтинг/.env` ← `инвайтинг/.env.example`
- `shadowchat/.env` ← `shadowchat/.env.example`
- `verdi-connector/.env` ← `verdi-connector/.env.example` (только для локальной разработки)

`INV_CONNECTOR_SYNC_SECRET` в инвайтинге должен совпадать с `INVITE_SYNC_SECRET` на Render API.

### Типичный сценарий

1. **Инвайтинг (ПК):** загрузка базы → инвайт в канал → отписка outreach-аккаунтами.
2. **Автосинк:** после отписки чат попадает в Operator Inbox на Render.
3. **Оператор (телефон/ПК):** открыть инбокс в браузере, ответить клиенту.
4. **Код (мобильный Cursor):** правки логики, UI, скриптов → push → pull на ПК.

### Важно

- Одну Telethon-сессию нельзя одновременно держать на ПК и Render — будет `AuthKeyDuplicatedError`.
- Для ответов в инбоксе используйте рабочие tech-аккаунты (tech_4/5/6), не сожжённые inviter/outreach.

## Быстрый старт ShadowChat

```bash
cd "Клонер чатов/shadowchat"
cp .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
start.bat
```

Подробнее: [shadowchat/README.md](shadowchat/README.md)

## Быстрый старт Инвайтинг

```bash
cd инвайтинг
cp .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
start.bat
```

Подробнее: [инвайтинг/README.md](../инвайтинг/README.md)

## Operator Inbox (Render + локально)

- Прод: https://verdi-connector-web.onrender.com/inbox
- Локально: `verdi-connector/start-local.bat` → http://localhost:3000

Подробнее: [verdi-connector/README.md](../verdi-connector/README.md)
