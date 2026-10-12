import asyncio
import logging

from sqlalchemy import select

from app.broker.rabbit import PAYMENTS_NEW_QUEUE, broker, payments_exchange
from app.database import async_session_factory
from app.models import Outbox

logger = logging.getLogger(__name__)


async def _publish_pending_batch(batch_size: int = 100) -> int:
    """Возвращает число опубликованных событий."""
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Outbox)
                .where(Outbox.published.is_(False))
                .order_by(Outbox.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            events = list(result.scalars().all())
            if not events:
                return 0

            for event in events:
                await broker.publish(
                    event.payload,
                    exchange=payments_exchange,
                    routing_key="payments.new",
                    headers={"event_type": event.event_type},
                )
                event.published = True

        return len(events)


async def run_outbox_publisher(interval: float = 1.0) -> None:
    await broker.connect()
    logger.info("Outbox publisher started")
    try:
        while True:
            try:
                published = await _publish_pending_batch()
                if published:
                    logger.info("Published %s outbox events", published)
            except Exception:
                logger.exception("Outbox publish error")
            await asyncio.sleep(interval)
    finally:
        await broker.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_outbox_publisher())