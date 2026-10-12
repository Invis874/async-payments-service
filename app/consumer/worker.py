import logging
from datetime import datetime, timezone

from faststream import FastStream
from faststream.rabbit import RabbitMessage, RabbitRouter

from app.broker.rabbit import (
    PAYMENTS_DLQ,
    PAYMENTS_NEW_QUEUE,
    broker,
    payments_dlx,
    payments_exchange,
)
from app.consumer.gateway import process_payment
from app.consumer.webhook import send_webhook
from app.database import async_session_factory
from app.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
router = RabbitRouter()


async def _load_payment(payment_id: str) -> Payment | None:
    async with async_session_factory() as session:
        return await session.get(Payment, payment_id)


async def _mark_status(
    payment_id: str, status: PaymentStatus, *, metadata: dict | None = None
) -> Payment | None:
    async with async_session_factory() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            return None
        payment.status = status
        payment.processed_at = datetime.now(timezone.utc)
        if metadata:
            payment.payment_metadata = {**payment.payment_metadata, **metadata}
        await session.commit()
        await session.refresh(payment)
        return payment


@router.subscriber(
    PAYMENTS_NEW_QUEUE,
    exchange=payments_exchange,
    # DLQ-очередь нам нужна только чтобы FastStream её объявил.
    # Реальная маршрутизация — через x-dead-letter-exchange на основной очереди.
    # (в 0.5.x есть возможность задекларировать доп. очередь через router)
)
async def handle_payment_new(body: dict, message: RabbitMessage) -> None:
    payment_id: str = body["payment_id"]
    headers = dict(message.headers or {})
    attempt = int(headers.get("x-retry-count", 0)) + 1

    logger.info("Processing payment %s (attempt %s)", payment_id, attempt)

    payment = await _load_payment(payment_id)
    if payment is None:
        logger.error("Payment %s not found, dropping message", payment_id)
        await message.ack()
        return

    # 1) Эмуляция платежного шлюза
    try:
        success = await process_payment()
    except Exception:
        logger.exception("Gateway crashed for %s", payment_id)
        success = False

    new_status = PaymentStatus.SUCCEEDED if success else PaymentStatus.FAILED
    payment = await _mark_status(payment_id, new_status)
    assert payment is not None

    # 2) Webhook
    webhook_payload = {
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount": str(payment.amount),
        "currency": payment.currency.value,
        "processed_at": payment.processed_at.isoformat()
        if payment.processed_at
        else None,
    }

    delivered = await send_webhook(payment.webhook_url, webhook_payload)

    if delivered:
        await message.ack()
        return

    # 3) Webhook не доставлен — решаем: retry или DLQ
    if attempt >= MAX_ATTEMPTS:
        logger.error(
            "Payment %s: webhook failed after %s attempts -> DLQ", payment_id, attempt
        )
        # requeue=False + настроенный x-dead-letter-exchange на очереди => уедет в DLQ
        await message.nack(requeue=False)
        return

    logger.warning(
        "Payment %s: webhook failed, requeue with attempt=%s", payment_id, attempt
    )
    # Публикуем копию с увеличенным счётчиком (requeue=True в RabbitMQ не даёт
    # удобно менять headers), и ack'аем исходное.
    await broker.publish(
        body,
        exchange=payments_exchange,
        routing_key="payments.new",
        headers={**headers, "x-retry-count": attempt},
    )
    await message.ack()


# Регистрируем DLQ-очередь, чтобы FastStream её декларировал при старте
#router.subscriber(PAYMENTS_DLQ, exchange=payments_dlx)
broker.include_router(router)

app = FastStream(broker)


@app.after_startup
async def _register_queues() -> None:
    """Декларируем exchanges, очереди и биндинги ПОСЛЕ подключения к RabbitMQ."""
    exchange = await broker.declare_exchange(payments_exchange)
    queue = await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    await queue.bind(exchange, routing_key="payments.new")

    dlx = await broker.declare_exchange(payments_dlx)
    dlq = await broker.declare_queue(PAYMENTS_DLQ)
    await dlq.bind(dlx, routing_key="payments.new.dlq")


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(app.run())