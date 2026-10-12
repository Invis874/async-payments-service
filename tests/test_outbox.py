import pytest
from sqlalchemy import select

from app.api.v1 import payments as payments_module
from app.models import Outbox, Payment


@pytest.mark.asyncio
async def test_outbox_event_created(
    client, idempotency_headers, session_factory, mocker
):
    # не даём outbox publisher'у реально ходить в RabbitMQ во время теста
    mocker.patch.object(payments_module, "Outbox", Outbox)

    r = await client.post(
        "/api/v1/payments",
        json={
            "amount": "5.00",
            "currency": "RUB",
            "webhook_url": "https://example.com/hook",
        },
        headers=idempotency_headers,
    )
    assert r.status_code == 202

    async with session_factory() as session:
        events = (await session.execute(select(Outbox))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "payment.new"
        assert "payment_id" in events[0].payload
        assert events[0].published is False

        payments = (await session.execute(select(Payment))).scalars().all()
        assert len(payments) == 1