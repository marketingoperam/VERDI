# Парсер Telegram-проектов конкурентов

Собирает карту проекта по одной ссылке: чаты, каналы, боты, описания, участники, ссылки из сообщений и кнопок.

## Рекомендуемый способ — Telegram Web (без api_id)

**Не нужен** my.telegram.org. Достаточно номера телефона и кода из Telegram — как при обычном входе на [web.telegram.org](https://web.telegram.org/k/).

### Установка

```bash
cd "Телеграм конкуренты"
pip install -r requirements.txt
python -m playwright install chromium
```

### Запуск

```bash
python parser_telegram_web.py --phone "+79XXXXXXXXX" --url "https://t.me/instachat6"
```

1. Откроется браузер с Telegram Web.
2. Скрипт введёт номер и запросит код.
3. Пришлите код: `python parser_telegram_web.py --phone "+79..." --code 12345 --url "https://t.me/instachat6"`

Или положите в `.env`:

```env
TG_PHONE=+79XXXXXXXXX
TG_CODE=12345
```

Сессия сохраняется в `sessions/tg_web_profile/` — повторный код не нужен.

### Только вход (без парсинга)

```bash
python parser_telegram_web.py --phone "+79..." --code 12345 --login-only
```

## Альтернатива — Telethon (нужен api_id)

Если получится создать приложение на [my.telegram.org/apps](https://my.telegram.org/apps):

```bash
python tg_login.py
python parser_telegram_project.py --url "https://t.me/instachat6"
```

## Результаты

В `output/`:

- `*_web_*.json` — полный дамп
- `*_entities.csv` — таблица для Excel
- `*_summary.md` — краткая сводка

## Ограничения

- Номер **один не достаточен** — Telegram всегда присылает код подтверждения.
- Приватные чаты без доступа — только превью или ошибка.
- Для ботов нужен вход в аккаунт (веб-версия это поддерживает).
