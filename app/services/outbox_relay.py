import asyncio
import json
import logging
from datetime import datetime, timezone
import aio_pika
from sqlalchemy import select
from app.config import settings
from app.db.models import OutboxMessage
from app.db.session import SessionLocal
from app.messaging import EXCHANGE_NAME, ROUTING_KEY, declare_topology

logger = logging.getLogger(__name__)

async def publish_pending(exchange, batch_size: int) -> int:
    async with SessionLocal() as session:
        async with session.begin():
            stmt = (
                select(OutboxMessage).where(OutboxMessage.published_at.is_(None))
                .order_by(OutboxMessage.created_at.asc()).limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.scalars(stmt)).all()
            if not rows:
                return 0
            for row in rows:
                body = {"event": row.payload, "attempt": 1}
                message = aio_pika.Message(
                    body=json.dumps(body, default=str).encode(),
                    delivery_mode=2, content_type="application/json",
                )
                await exchange.publish(message, routing_key=ROUTING_KEY, mandatory=True)
                row.published_at = datetime.now(timezone.utc)
                row.last_error = None
            return len(rows)

async def outbox_relay_loop() -> None:
    while True:
        connection = None
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            channel = await connection.channel()
            await declare_topology(channel)
            exchange = await channel.get_exchange(EXCHANGE_NAME)
            while True:
                published = await publish_pending(exchange, settings.outbox_batch_size)
                if published == 0:
                    await asyncio.sleep(settings.outbox_poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox relay failed, retrying in 2 seconds")
            await asyncio.sleep(2)
        finally:
            if connection is not None:
                try:
                    await connection.close()
                except Exception:
                    pass
