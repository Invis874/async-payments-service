import asyncio
import random


async def process_payment() -> bool:
    """Эмуляция обработки: 2-5 секунд, 90% успех."""
    await asyncio.sleep(random.uniform(2.0, 5.0))
    return random.random() < 0.9