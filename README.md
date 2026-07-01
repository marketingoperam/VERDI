# AI-поисковик конкурентов (Verdi Monitor)

Веб-сервис для мониторинга конкурентов по **Google**, **Яндекс**, **VK** и **Telegram** с AI-анализом находок.

## Стек

- **Backend:** FastAPI, SQLAlchemy async, PostgreSQL
- **Workers:** Celery + Redis
- **Frontend:** React, Vite, TailwindCSS
- **Collectors:** Google Custom Search, Yandex Search API, VK API, Telethon

## Быстрый старт (Docker)

```bash
cp .env.example .env
# Заполните API-ключи в .env

docker compose up --build
```

- Панель: http://localhost:5173
- API: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Локальная разработка

### 1. PostgreSQL и Redis

```bash
docker compose up db redis -d
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
set PYTHONPATH=..;.   # Windows
# export PYTHONPATH=..:.  # Linux/macOS
uvicorn app.main:app --reload --port 8000
```

### 3. Worker

```bash
cd backend
celery -A workers.tasks:celery_app worker --loglevel=info
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Telegram-сессия

```bash
cd backend
python scripts/telegram_login.py
```

## Настройка API-ключей

Скопируйте `.env.example` → `.env` и заполните:

| Переменная | Описание |
|---|---|
| `GOOGLE_API_KEY`, `GOOGLE_CX` | [Google Custom Search](https://developers.google.com/custom-search) |
| `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` | [Yandex Search API](https://yandex.cloud/ru/docs/search-api/) |
| `VK_ACCESS_TOKEN` | [VK API](https://dev.vk.com/) |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org/) |
| `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` | OpenAI-совместимый API |

Ключи также можно задать через UI в разделе **Settings**.

## Сценарий использования

1. **Search** → добавьте конкурента (бренд, ключи, VK/Telegram).
2. **Search** → нажмите «Все источники» или отдельный коллектор.
3. **Feed** → смотрите находки с AI-summary, tone, offer, CTA.
4. **Analytics** → сводка за 24 часа и тренды.
5. **Settings** → ключи и интервал фонового мониторинга.

## Структура

```
backend/
  app/           # FastAPI, модели, API
  collectors/    # google, yandex, vk, telegram, ai_analyzer
  scripts/       # telegram_login.py
frontend/        # React-панель
workers/         # Celery tasks
docker-compose.yml
```

## API

- `GET/POST/PUT/DELETE /api/v1/competitors`
- `POST /api/v1/search/run-{all|google|yandex|vk|telegram}`
- `GET /api/v1/findings` (фильтры: source, competitor_id, tone, q, …)
- `GET /api/v1/analytics/summary`
- `GET/PUT /api/v1/settings`

## Примечания

- Дедупликация по `source + external_id` или hash текста/URL.
- Telegram требует предварительной авторизации (`telegram_login.py`).
- VK `wall.get` для групп использует отрицательный `owner_id`.
- Фоновый мониторинг запускается Celery Beat по `MONITOR_INTERVAL_HOURS`.
