import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import api_router
from app.db.session import engine
from app.services.outbox_relay import outbox_relay_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    relay_task = asyncio.create_task(outbox_relay_loop())

    yield

    relay_task.cancel()
    try:
        await relay_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


app = FastAPI(
    title="Async Payment Processing Service",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}