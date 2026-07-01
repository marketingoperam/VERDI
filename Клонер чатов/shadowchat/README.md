# ShadowChat

Внутренняя система зеркалирования Telegram-чатов для онбординга новых сотрудников.

Сообщения из исходных рабочих чатов копируются в обучающие зеркальные чаты в почти реальном времени (event-driven, целевая задержка 1–3 сек). Каждый сотрудник закреплён за одним техническим аккаунтом на постоянной основе.

## Стек

- Python 3.11+
- Telethon (MTProto)
- FastAPI + SQLAlchemy (async) + Alembic
- PostgreSQL + Redis
- Docker Compose

## Панель управления

После запуска откройте в браузере:

**http://localhost:8000**

Веб-панель позволяет без кода:
- добавлять пары чатов (исходный → зеркало) в один клик;
- управлять техническими аккаунтами и привязкой к сотрудникам;
- видеть журнал репликации и статус системы;
- настраивать фильтры и режим удаления;
- следовать пошаговому чеклисту на главной странице.

Для запуска дважды кликните `start.bat` — он откроет панель автоматически.

## Быстрый старт

### 1. Настройка окружения

```bash
cd shadowchat
cp .env.example .env
# Заполните LISTENER_API_ID, LISTENER_API_HASH и DATABASE_URL
```

Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).

### 2. Авторизация listener-сессии

```bash
pip install -r requirements.txt
python scripts/auth_session.py --session listener_main
```

Повторите для каждого технического аккаунта из пула (`--session tech_user_01` и т.д.).

### 3. Запуск через Docker

```bash
docker compose up -d
```

Сервисы:
- **API + Listener**: `http://localhost:8000`
- **Healthcheck**: `GET /health`
- **Документация**: `http://localhost:8000/docs`

### 4. Настройка чатов через API

```bash
# Создать зеркальный чат
curl -X POST http://localhost:8000/api/v1/mirror-chats \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id": -1001234567890, "title": "Онбординг / Продажи", "mode": "safe"}'

# Создать исходный чат и привязать к зеркалу
curl -X POST http://localhost:8000/api/v1/source-chats \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id": -1009876543210, "title": "Продажи", "mirror_chat_id": 1}'

# Добавить техническую сессию и закрепить за сотрудником
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_name": "tech_user_01", "api_id": 12345, "api_hash": "...", "assigned_employee_id": 1}'
```

## Режимы зеркалирования

### Safe (по умолчанию)

Сообщения публикуются с явной пометкой автора:

```text
[Отдел продаж / Иван Петров]
11:42
Клиент просит КП до вечера.
```

### Profile Sync (опционально)

Включается через `PROFILE_SYNC_ENABLED=true` и `mode: "profile_sync"` на зеркальном чате. Синхронизирует имя и аватар на техническом аккаунте (не чаще 1 раза в 24 часа).

## API

| Метод | Путь | Описание |
|-------|------|----------|
| GET/POST/PUT | `/api/v1/source-chats` | Исходные чаты |
| GET/POST/PUT | `/api/v1/mirror-chats` | Зеркальные чаты |
| GET/POST/PUT | `/api/v1/employees` | Сотрудники |
| GET/POST/PUT | `/api/v1/sessions` | Пул технических сессий |
| GET | `/api/v1/logs` | Журнал репликации |
| GET/PUT | `/api/v1/settings` | Настройки |
| GET | `/health` | Healthcheck |

## Архитектура

```text
Listener (Telethon) → Dispatcher → MirrorSender → Зеркальный чат
                         ↓
                   EmployeeBinding (permanent 1:1)
                         ↓
                   MessageMap (reply-цепочки)
```

## Настройки (.env)

| Переменная | Описание |
|------------|----------|
| `DELETE_MODE` | `soft_delete` или `hard_delete` |
| `IGNORE_BOTS` | Игнорировать сообщения ботов |
| `IGNORE_SERVICE_MESSAGES` | Игнорировать сервисные сообщения |
| `MESSAGE_FILTER_MODE` | `all`, `text_only`, `min_length` |
| `PROFILE_SYNC_ENABLED` | Синхронизация профилей (false по умолчанию) |

## Важно

- Используйте только с согласия сотрудников, чьи сообщения зеркалируются.
- Listener-аккаунт должен быть участником всех исходных чатов.
- Технические аккаунты — участники зеркальных чатов.
- Один технический аккаунт = один сотрудник (permanent binding).

## Локальная разработка

```bash
# Миграции
alembic upgrade head

# API
uvicorn app.main:app --reload

# Только listener
python run_listener.py
```

## Profile sync worker

```bash
docker compose --profile profile-sync up -d profile-worker
```
