# Деплой VERDI Operator Inbox на Render.com

Сайт: `https://verdi-connector-web.onrender.com`  
API: `https://verdi-connector-api.onrender.com`

Логин: `andf1n@verdi.local` / `admin123`

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
