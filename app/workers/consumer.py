import asyncio
import json
import logging
import aio_pika
from faststream import FastStream
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue
from app.config import settings
from app.messaging import (
    DEAD_ROUTING_KEY, DLX_EXCHANGE_NAME, EXCHANGE_NAME, MAX_ATTEMPTS,
    QUEUE_NAME, RETRY_DELAYS_MS, ROUTING_KEY, declare_topology, retry_routing_key,
)
from app.services.processing import process_payment_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

broker = RabbitBroker(settings.rabbitmq_url)
app = FastStream(broker)

queue = RabbitQueue(
    QUEUE_NAME, durable=True, routing_key=ROUTING_KEY,
    arguments={"x-dead-letter-exchange": DLX_EXCHANGE_NAME, "x-dead-letter-routing-key": DEAD_ROUTING_KEY},
)
exchange = RabbitExchange(EXCHANGE_NAME, durable=True, type=ExchangeType.DIRECT)

_publish_connection = None
_publish_channel = None
_main_exchange = None
_dlx_exchange = None
_publish_lock = asyncio.Lock()

async def ensure_publish_channel():
    global _publish_connection, _publish_channel, _main_exchange, _dlx_exchange
    async with _publish_lock:
        if _publish_channel is None or getattr(_publish_channel, "is_closed", False):
            if _publish_connection is not None:
                try: await _publish_connection.close()
                except Exception: pass
            _publish_connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            _publish_channel = await _publish_connection.channel()
            await declare_topology(_publish_channel)
            _main_exchange = await _publish_channel.get_exchange(EXCHANGE_NAME)
            _dlx_exchange = await _publish_channel.get_exchange(DLX_EXCHANGE_NAME)
    return _main_exchange, _dlx_exchange

async def publish_json(exchange, routing_key: str, body: dict) -> None:
    message = aio_pika.Message(
        body=json.dumps(body, default=str).encode(),
        delivery_mode=2, content_type="application/json",
    )
    await exchange.publish(message, routing_key=routing_key, mandatory=True)

@app.on_shutdown
async def close_publish_connection():
    global _publish_channel, _publish_connection
    if _publish_channel is not None:
        try: await _publish_channel.close()
        except Exception: pass
    if _publish_connection is not None:
        try: await _publish_connection.close()
        except Exception: pass

@broker.subscriber(queue=queue, exchange=exchange)
async def consume_payment_event(message_body: dict):
    if not isinstance(message_body, dict):
        if isinstance(message_body, (bytes, bytearray, str)):
            try: message_body = json.loads(message_body)
            except Exception: message_body = {}
        else: message_body = {}

    try: attempt = max(1, int(message_body.get("attempt", 1)))
    except Exception: attempt = 1

    event = message_body.get("event") or {}

    try:
        await process_payment_event(event)
    except Exception:
        logger.exception("Payment event processing failed, attempt=%s", attempt)
        try:
            if attempt < MAX_ATTEMPTS:
                delay_ms = RETRY_DELAYS_MS[min(attempt - 1, len(RETRY_DELAYS_MS) - 1)]
                retry_body = dict(message_body)
                retry_body["attempt"] = attempt + 1
                main_exchange, _ = await ensure_publish_channel()
                await publish_json(main_exchange, retry_routing_key(delay_ms), retry_body)
                logger.info("Scheduled retry #%s with delay %sms", attempt + 1, delay_ms)
            else:
                _, dlx_exchange = await ensure_publish_channel()
                await publish_json(dlx_exchange, DEAD_ROUTING_KEY, message_body)
                logger.error("Message moved to DLQ after %s attempts", attempt)
        except Exception:
            logger.exception("Failed to schedule retry or publish to DLQ")
            raise

if __name__ == "__main__":
    asyncio.run(app.run())
