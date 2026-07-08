# Деплой VERDI Operator Inbox на Render.com

Сайт: `https://verdi-connector-web.onrender.com`  
API: `https://verdi-connector-api.onrender.com`

Логин: `andf1n@verdi.local` / `admin123`

## Инвайтинг → Inbox (холодная отписка)

После отписки из панели `инвайтинг` диалог появляется в [Operator Inbox](https://verdi-connector-web.onrender.com/inbox) с синей точкой (`state=new`).

### Env

| Сервис | Key | Value |
|--------|-----|--------|
| **verdi-connector-api** | `INVITE_SYNC_SECRET` | один длинный секрет |
| **инвайтинг `.env`** | `INV_CONNECTOR_API_URL` | `https://verdi-connector-api.onrender.com` |
| **инвайтинг `.env`** | `INV_CONNECTOR_SYNC_SECRET` | тот же секрет |

### Ответы из Inbox (outreach-аккаунты)

Чтобы отвечать из Inbox и получать входящие на outreach-аккаунте:

1. Экспорт сессии из инвайтинга:
   ```powershell
   cd инвайтинг
   .\.venv\Scripts\python.exe scripts\export_session_b64.py outreach1
   ```
2. На Render API: `TELEGRAM_SESSION_STRING_outreach1` = содержимое `.telegram-sessions/outreach1.string.txt`
3. Добавить `outreach1` в `TELEGRAM_SESSIONS` (через запятую)
4. **Не запускать тот же outreach локально и на Render одновременно** (AuthKeyDuplicated)

### Ручная догрузка уже отписанного

`POST http://127.0.0.1:8010/api/v1/targets/{id}/sync-inbox`

## Telegram в облаке (@andf1n)

На API крутится Telethon-воркер с сессией `listener_main` (аккаунт `@andf1n`).

### Важно

1. **Не держите одну и ту же сессию одновременно на ПК и на Render.** Пока тестируете облако — остановите локальный ShadowChat / listener с `listener_main`, иначе Telegram может кикнуть сессию.
2. Сессию **не коммитим** в GitHub. Только Secret / Env на Render.

### Env на verdi-connector-api

| Key | Value |
|-----|--------|
| `CORS_ORIGIN` | `https://verdi-connector-web.onrender.com` |
| `TELEGRAM_USE_STUB` | `false` |
| `TELEGRAM_SESSION` | `listener_main` |
| `TELEGRAM_API_ID` | `30268202` |
| `TELEGRAM_API_HASH` | из ShadowChat `.env` (`LISTENER_API_HASH`) |
| `TELEGRAM_SESSION_B64` | base64 файла `listener_main.session` (см. ниже) |

### Как получить TELEGRAM_SESSION_B64 (Windows PowerShell)

```powershell
[Convert]::ToBase64String(
  [IO.File]::ReadAllBytes(
    "C:\Users\Karim\Desktop\Verdi\Клонер чатов\shadowchat\sessions\listener_main.session"
  )
) | Set-Clipboard
```

Вставьте из буфера в Render → **verdi-connector-api** → Environment → `TELEGRAM_SESSION_B64` → Save → Manual Deploy.

### Web env

| Key | Value |
|-----|--------|
| `NEXT_PUBLIC_API_URL` | `https://verdi-connector-api.onrender.com` |
| `NEXT_PUBLIC_WS_URL` | `https://verdi-connector-api.onrender.com` |

## Первый деплой / обновление Blueprint

1. Commit+push папки `verdi-connector/` (латиница) в GitHub.
2. Render → Blueprint / Manual Deploy сервисов.
3. Прописать env из таблиц выше (особенно `TELEGRAM_API_HASH` и `TELEGRAM_SESSION_B64`).
4. Дождаться Deploy Live у API, открыть web, залогиниться.
5. В логах API должно быть: `Telegram worker ready @andf1n`.
6. Напишите себе в Telegram с другого аккаунта — диалог появится в inbox.

## Free tier

После ~15 мин бездействия сервис «засыпает». Пока оператор на сайте — обычно ок. Первый заход после сна: 30–60 сек.

## Свой домен (SprintHost)

1. Render → web → Custom Domain.
2. В SprintHost DNS: CNAME на `verdi-connector-web.onrender.com`.
