from faststream.rabbit import (
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)

from app.config import settings

# Broker
broker = RabbitBroker(settings.rabbit_url)

# Exchanges
payments_exchange = RabbitExchange(
    "payments", type=ExchangeType.DIRECT, durable=True
)
payments_dlx = RabbitExchange(
    "payments.dlx", type=ExchangeType.DIRECT, durable=True
)

# Main queue с DLX-настройками:
# если consumer сделает nack(requeue=False) — сообщение уедет в DLQ
PAYMENTS_NEW_QUEUE = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key="payments.new",
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payments.new.dlq",
    },
)

PAYMENTS_DLQ = RabbitQueue(
    "payments.new.dlq",
    durable=True,
    routing_key="payments.new.dlq",
)