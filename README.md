# Async Payments Service

Микросервис асинхронной обработки платежей. Принимает платёж, публикует событие через Outbox, эмулирует обработку во внешнем шлюзе, уведомляет клиента через webhook с retry и DLQ.

## Стек

- **FastAPI** + **Pydantic v2**
- **SQLAlchemy 2.0** (async) + **PostgreSQL**
- **RabbitMQ** + **FastStream**
- **Alembic** для миграций
- **Docker** + **docker-compose**

## Архитектура

```
 Client ──► POST /api/v1/payments ──► API (FastAPI)
                                        │  одна транзакция:
                                        │   INSERT payments
                                        │   INSERT outbox
                                        ▼
                                     PostgreSQL
                                        ▲
                                        │ FOR UPDATE SKIP LOCKED
                                        │
                              outbox publisher (в api)
                                        │
                                        ▼ publish
                                     RabbitMQ
                                     payments.new
                                        │
                                        ▼
                                    consumer (FastStream)
                                        │
                                        ├─► emulate gateway (2-5 s, 90% ok)
                                        ├─► UPDATE payments.status
                                        └─► POST webhook (retry ×3, exp backoff)
                                              │
                                              ├─ 2xx/3xx/4xx: ack
                                              ├─ fail & attempts < 3: republish (x-retry-count)
                                              └─ fail & attempts >= 3: nack(requeue=False)
                                                                        ▼
                                                                   payments.dlx
                                                                        ▼
                                                                   payments.new.dlq
```

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000/docs
- RabbitMQ management: http://localhost:15672 (guest / guest)
- Postgres: localhost:5432 (payments / payments)

Миграции применяются автоматически при старте сервиса `api`.

## API

Все эндпоинты защищены заголовком `X-API-Key`.

### Создание платежа

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: super-secret-api-key" \
  -H "Idempotency-Key: order-42-attempt-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "USD",
    "description": "Order #42",
    "metadata": {"order_id": "42"},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "d3f1...",
  "status": "pending",
  "created_at": "2026-01-01T12:00:00+00:00"
}
```

Повторный запрос с тем же `Idempotency-Key` вернёт **тот же** `payment_id`.

### Получение платежа

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: super-secret-api-key"
```

## Тесты

```bash
# Создать и активировать виртуальное окружение
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
pytest -v
```

Тесты используют SQLite in-memory, RabbitMQ и webhook HTTP-вызовы мокаются.

## Локальный приёмник вебхуков

Внешние сервисы вида webhook.site могут быть недоступны из отдельных сетей (VPN, firewall, санкционные ограничения). Для локальной проверки есть скрипт `scripts/webhook_receiver.py` — он слушает `http://0.0.0.0:9999/webhook` и печатает входящие POST в консоль.

Запуск **на хосте** (не в Docker):

```bash
python scripts/webhook_receiver.py
```

Использование в запросе:

```json
"webhook_url": "http://host.docker.internal:9999/webhook"
```

`host.docker.internal` — специальное имя, по которому контейнер видит хост-машину (работает в Docker Desktop на Windows/Mac). На Linux используйте IP хоста из `ip addr`.

## Быстрая проверка

```bash
# 0. Поднять
cp .env.example .env
docker compose up --build -d

# 1. Запустить локальный приёмник вебхуков в отдельном окне
python scripts/webhook_receiver.py

# 2. Создать платёж
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: super-secret-api-key" \
  -H "Idempotency-Key: quick-test-1" \
  -H "Content-Type: application/json" \
  -d '{"amount":"100.50","currency":"USD","webhook_url":"http://host.docker.internal:9999/webhook"}'
# → 202, запомни payment_id

# 3. Через 5 секунд проверить статус
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: super-secret-api-key"
# → status: succeeded (или failed), processed_at не null

# 4. Проверить идемпотентность (тот же ключ → тот же payment_id, нового вебхука нет)
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: super-secret-api-key" \
  -H "Idempotency-Key: quick-test-1" \
  -H "Content-Type: application/json" \
  -d '{"amount":"100.50","currency":"USD","webhook_url":"http://host.docker.internal:9999/webhook"}'

# 5. Проверить DLQ (битый webhook URL → 3 retry → DLQ)
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: super-secret-api-key" \
  -H "Idempotency-Key: quick-test-dlq" \
  -H "Content-Type: application/json" \
  -d '{"amount":"50.00","currency":"EUR","webhook_url":"http://127.0.0.1:1/hook"}'
# подожди 15 секунд
docker compose exec rabbitmq rabbitmqctl list_queues name messages
# → payments.new: 0, payments.new.dlq: 1
```

## Принятые решения

| Требование | Реализация |
|---|---|
| Idempotency key | Уникальный индекс по `payments.idempotency_key`, при повторе возвращаем существующий платёж (202). |
| Outbox pattern | Таблицы `payments` + `outbox` пишутся в одной транзакции. Фоновый воркер читает `outbox` c `FOR UPDATE SKIP LOCKED` и публикует в RabbitMQ. |
| Retry | Webhook ретраится до 3 раз с экспоненциальной задержкой (1s → 2s). При исчерпании попыток — сообщение уходит в DLQ. |
| DLQ | У основной очереди настроен `x-dead-letter-exchange=payments.dlx`. При `nack(requeue=False)` сообщение попадает в `payments.new.dlq`. |
| Гарантия доставки | Outbox + `publisher confirms` RabbitMQ (FastStream ждёт подтверждения публикации). |
| Аутентификация | Заголовок `X-API-Key` через FastAPI dependency. |

## Модель безопасности и мульти-тенантность

Текущая реализация — **single-tenant**: один экземпляр сервиса обслуживает одного мерчанта (один сайт). Это отражено в ТЗ: единственный статический `X-API-Key`, webhook URL передаётся в каждом запросе.

Если бы сервис обслуживал **несколько мерчантов** (SaaS-платформа), модель была бы другой:

- появилась бы таблица `merchants` (`id`, `name`, `api_key`, `webhook_secret`);
- `X-API-Key` был бы **per-merchant**, по нему мы находили бы мерчанта и привязывали к платежу `merchant_id`;
- `webhook_secret` тоже был бы **per-merchant**, потому что один общий секрет позволил бы мерчанту A подписывать вебхуки, которые мерчант B принял бы как валидные.

Ключевое правило: **секрет для подписи исходящего вебхука — это свойство получателя (мерчанта), а не сервиса**. В single-tenant получатель один → секрет один → хватило бы `.env`. В multi-tenant получателей много → секреты живут в БД, по строке на мерчанта.

### Где хранятся секреты в single- vs multi-tenant

| | Single-tenant (наш случай) | Multi-tenant |
|---|---|---|
| Мерчантов | 1 | Много |
| `X-API-Key` | один, в `.env` | свой у каждого, в `merchants.api_key` |
| `webhook_secret` | один, в `.env` | свой у каждого, в `merchants.webhook_secret` |
| Таблица `merchants` | не нужна | нужна |
| `payments.merchant_id` | не нужен | нужен |

## Что добавили бы в проде

В ТЗ этих пунктов нет, поэтому в текущей реализации они **осознанно не сделаны** — чтобы не выходить за рамки задания и не тащить лишний код. Но в реальном платёжном сервисе мы бы их закрыли.

### 1. HMAC-подпись исходящих вебхуков

Сейчас вебхуки не подписаны. Получатель (сайт-мерчант) не может отличить настоящий вебхук от поддельного, если URL утечёт.

В проде добавили бы:

- заголовок `X-Webhook-Signature: t=<unix_ts>,v1=<hex>` — HMAC-SHA256 по строке `f"{ts}.{raw_body}"`;
- заголовок `X-Webhook-Timestamp: <unix_ts>` — timestamp внутри подписи защищает от replay-атак (получатель отвергает вебхуки старше N секунд);
- на стороне получателя сверку делают через `hmac.compare_digest` (constant-time, чтобы не текла информация через тайминг);
- **важно:** тело сериализуется **один раз**, и те же байты идут и в подпись, и в HTTP-запрос. Иначе `{"a":1}` vs `{"a": 1}` ломают подпись.

Где хранить секрет — зависит от модели:

- **single-tenant** (наш случай): один секрет в `.env`, подписываем им все вебхуки;
- **multi-tenant**: секрет per-merchant в `merchants.webhook_secret`, подписываем секретом того мерчанта, которому принадлежит платёж (`payment.merchant.webhook_secret`).

В проде `webhook_secret` дополнительно шифруют at-rest (KMS / pgcrypto), чтобы дамп БД не раскрывал секреты.

### 2. Отдельный воркер `outbox-publisher`

Сейчас outbox-publisher живёт **внутри API** как фоновая задача (FastAPI `lifespan`). Это безопасно (используем `FOR UPDATE SKIP LOCKED`), но при рестарте API публикация встаёт на пару секунд.

В проде вынесли бы publisher в отдельный контейнер `outbox-publisher` в `docker-compose.yml` — чтобы API только принимал запросы, а публикация в RabbitMQ не зависела от рестартов API.

### 3. Метрики и структурное логирование

Сейчас — стандартный `logging` из stdlib. В проде добавили бы:

- Prometheus-метрики: `payments_created_total`, `payments_succeeded_total`, `payments_failed_total`, `webhook_delivery_seconds` (histogram), `outbox_pending_gauge`, `dlq_size`;
- `structlog` для JSON-логов с `payment_id`, `merchant_id`, `attempt` в каждом сообщении — чтобы искать в ELK/Loki по платёжке.

### 4. Идемпотентность с телом запроса

Сейчас идемпотентность проверяется **только по `Idempotency-Key`**. Если тот же ключ придёт с другим телом, вернём тот же платёж — потенциально не то, что ожидал клиент. В проде:

- хранили бы `hash(body)` рядом с ключом;
- при повторе сравнивали бы хеши: совпадают — возвращаем платёж, не совпадают — `409 Conflict`.

### 5. Ротация API-ключей и секретов

В single-tenant это одна строка в `.env`, менять руками и перезапускать сервис. В multi-tenant — endpoint на ротацию, поддержка двух активных ключей одновременно (плавная ротация без даунтайма), журнал «когда ротировали».

### 6. Rate limiting

Публичный API без ограничений легко положить залпом запросов. В проде — token bucket на мерчанта (через Redis + `slowapi` или nginx `limit_req`).