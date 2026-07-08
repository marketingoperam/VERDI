# Деплой VERDI Operator Inbox на Render.com

Панель будет доступна по ссылке вида `https://verdi-connector-web.onrender.com` постоянно (месяц+), пока сервис не удалите.

## Важно перед стартом

1. Код должен быть в GitHub (репозиторий `marketingoperam/VERDI` у вас уже есть).
2. На **бесплатном** Render сервис может «засыпать» после ~15 минут бездействия — первый заход может подождать 30–60 сек. Для без «сна» нужен платный план (~$7/мес за web).
3. **Отправка сообщений в Telegram с Render** пока не подключена (сессии Telethon лежат у вас на ПК). На Render будет работать: **логин, диалоги, UI**. Отправка «по-настоящему» — отдельный шаг позже (воркер на ПК или GramJS).

## Шаги (мышка + копипаст)

### 1) Закоммитить `verdi-connector` в GitHub

Если папка ещё не в репозитории — попросите Cursor/агента сделать commit+push, или вручную:

```bat
cd C:\Users\Karim\Desktop\Verdi
git add "Клонер чатов/verdi-connector"
git commit -m "Add VERDI connector for Render deploy"
git push origin main
```

### 2) Создать аккаунт на https://render.com

Войти через GitHub.

### 3) New → Blueprint

1. **New** → **Blueprint**
2. Подключить репозиторий **VERDI**
3. Указать путь к файлу: `Клонер чатов/verdi-connector/render.yaml`  
   (если Blueprint не видит кириллицу в пути — создайте сервисы вручную, см. ниже)

### 4) После создания API — скопировать URL

В дашборде Render откройте сервис **verdi-connector-api**.  
Публичный URL будет примерно:

`https://verdi-connector-api.onrender.com`

### 5) Прописать CORS и ссылки API в Web

В **verdi-connector-api** → Environment:

| Key | Value |
|-----|--------|
| `CORS_ORIGIN` | `https://verdi-connector-web.onrender.com` |

(подставьте **точный** URL вашего web-сервиса)

В **verdi-connector-web** → Environment:

| Key | Value |
|-----|--------|
| `NEXT_PUBLIC_API_URL` | `https://verdi-connector-api.onrender.com` |
| `NEXT_PUBLIC_WS_URL` | `https://verdi-connector-api.onrender.com` |

Затем **Manual Deploy** → Clear build cache & deploy у **web**.

### 6) Открыть

Ссылка человеку: `https://verdi-connector-web.onrender.com`

Логин:
- Email: `andf1n@verdi.local`
- Password: `admin123`

## Если Blueprint с кириллицей не сработал — руками

### Postgres
**New** → **PostgreSQL** → Free → Create.

### API (Web Service)
- Root Directory: `Клонер чатов/verdi-connector/apps/api`
- Build: `npm install --include=dev && sed -i 's/provider = "sqlite"/provider = "postgresql"/' prisma/schema.prisma && npx prisma generate && npm run build`
- Start: `npx prisma db push && node dist/main.js`
- Env: `DATABASE_URL` = Internal Database URL из Postgres  
  + `USE_SYNC_OUTBOX=true`, `TELEGRAM_USE_STUB=true`, `JWT_SECRET=...`, `CORS_ORIGIN=...`

### Web (Web Service)
- Root Directory: `Клонер чатов/verdi-connector/apps/web`
- Build: `npm install --include=dev && npm run build`
- Start: `npx next start -H 0.0.0.0 -p $PORT`
- Env: `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` = URL API

## Потом ваш домен (SprintHost)

Когда web на Render заработает:
1. В Render → web → **Custom Domain** → ваш домен.
2. В SprintHost DNS: **CNAME** `www` (или как скажет Render) на `verdi-connector-web.onrender.com`.

## Локальная разработка после перехода на Postgres

Локально удобнее оставить SQLite (`file:./dev.db`).  
Для этого временно в `apps/api/prisma/schema.prisma` верните `provider = "sqlite"`  
или поднимите Postgres из `docker-compose.yml` и укажите `DATABASE_URL` как в compose.
