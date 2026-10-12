import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import api_router
from app.broker.publisher import run_outbox_publisher
from app.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запускаем outbox publisher как фоновую задачу
    task = asyncio.create_task(run_outbox_publisher(interval=1.0))
    logger.info("Outbox publisher task started")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Outbox publisher task stopped")


app = FastAPI(
    title="Async Payments Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok"}