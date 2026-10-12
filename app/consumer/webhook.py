import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


async def send_webhook(
    url: str,
    payload: dict,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    timeout: float = 10.0,
) -> bool:
    """
    Отправляет webhook. Успех = 2xx/3xx/4xx (клиентские ошибки не ретраим).
    Ретраим 5xx и сетевые ошибки с экспоненциальной задержкой.
    """
    delay = base_delay
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code < 500:
                    return True
                logger.warning(
                    "Webhook %s returned %s (attempt %s/%s)",
                    url,
                    resp.status_code,
                    attempt,
                    max_attempts,
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Webhook %s error: %s (attempt %s/%s)",
                    url,
                    exc,
                    attempt,
                    max_attempts,
                )

            if attempt < max_attempts:
                await asyncio.sleep(delay)
                delay *= 2

    return False