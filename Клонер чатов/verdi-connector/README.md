# VERDI Connector — Operator Inbox MVP

Production-like MVP коннектора между **техническим Telegram-аккаунтом** и **администраторами VERDI**.

Администратор ведёт личные диалоги с приглашёнными пользователями **через веб-панель** или **служебный Telegram-чат с командами**, не логинясь в техаккаунт вручную.

## Быстрый старт

### Вариант A — без Docker (Windows, только Node.js)

```bat
start-local.bat
```

Откройте **http://localhost:3000**

### Вариант B — Docker

```bash
copy .env.example .env
docker compose up --build
```

Логин по умолчанию:
- Email: `admin@verdi.local`
- Password: `admin123`

API: http://localhost:3001/api

## Архитектура

```
verdi-connector/
├── docker-compose.yml
├── .env.example
├── apps/
│   ├── api/                          # NestJS backend
│   │   ├── prisma/schema.prisma
│   │   └── src/
│   │       ├── main.ts
│   │       ├── app.module.ts
│   │       ├── config/
│   │       ├── prisma/
│   │       ├── bootstrap/
│   │       └── modules/
│   │           ├── auth/
│   │           ├── operators/
│   │           ├── technical-accounts/   # catalog controller
│   │           ├── leads/                # via conversations
│   │           ├── conversations/
│   │           ├── messages/             # via conversations
│   │           ├── outbox/
│   │           ├── templates/
│   │           ├── moderation/           # TODO: full workflow
│   │           ├── transport/
│   │           ├── policy/
│   │           ├── risk-control/
│   │           ├── audit-log/
│   │           ├── telegram-command-relay/
│   │           └── realtime/
│   └── web/                            # Next.js operator inbox
│       └── src/app/
│           ├── page.tsx                # login
│           └── inbox/page.tsx          # 3-column inbox
```

### Потоки данных

1. **Inbound**: `TelegramTransport` → `ConversationService` → DB + WebSocket
2. **Outbound**: Operator UI / `/reply` command → `OutboxService` → `PolicyEngine` → BullMQ → `TelegramTransport.sendMessage`
3. **Risk**: события повышают `riskScore`, policy может блокировать initiation
4. **Audit**: все ключевые действия пишутся в `AuditLog`

### Режимы безопасности

- `REPLY_ONLY=true` (по умолчанию) — только ответы в существующих диалогах
- Initiation проходит отдельную policy-проверку: лимиты, stop-list, expectedContact, riskScore
- Anti-burst, deduplication по `normalizedBody`, случайная задержка отправки

## Модули

| Модуль | Назначение |
|--------|------------|
| `transport` | Абстракция Telegram user-session |
| `policy` | Policy engine |
| `outbox` | Очередь исходящих + BullMQ processor |
| `conversations` | Inbound relay, inbox API |
| `telegram-command-relay` | Команды `/reply`, `/pause_account`, ... |
| `risk-control` | riskScore техаккаунта |
| `realtime` | WebSocket события |
| `web` | Панель оператора |

## Telegram commands (служебный чат)

```
/reply <conversationId> <text>
/note <conversationId> <text>
/assign <conversationId> <operatorId>
/pause_account <technicalAccountId>
/resume_account <technicalAccountId>
/stoplist <conversationId> <reason>
```

Для локальной отладки: `POST /api/telegram-commands/simulate`

## Dev / тест без реального Telegram

1. Войти в панель
2. `POST /api/transport/simulate-inbound` (admin) — создать входящее
3. Ответить из UI — outbox + policy + stub send

## TODO (следующие шаги)

- [ ] Реальный `TelegramUserSessionAdapter` на GramJS/MTProto
- [ ] Подключение служебного Telegram-чата к `TelegramCommandRelayService`
- [ ] Moderation workflow UI
- [ ] RBAC на уровне endpoint guards по операторам
- [ ] Rate limiting API (nestjs-throttler)

## Тесты

```bash
cd apps/api
npm install
npm test
```

## Переменные окружения

См. `.env.example`
