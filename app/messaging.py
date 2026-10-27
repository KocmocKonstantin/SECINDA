import aio_pika

EXCHANGE_NAME = "payments.events"
DLX_EXCHANGE_NAME = "payments.dlx"

QUEUE_NAME = "payments.new"
DLQ_NAME = "payments.new.dlq"

ROUTING_KEY = "payment.new"
DEAD_ROUTING_KEY = "payment.dead"

RETRY_DELAYS_MS = (1000, 2000, 4000)
MAX_ATTEMPTS = 3


def retry_queue_name(delay_ms: int) -> str:
    return f"payments.retry.{delay_ms}"


def retry_routing_key(delay_ms: int) -> str:
    return f"payment.retry.{delay_ms}"


async def declare_topology(channel):
    """
    Объявляет обменники, основную очередь, DLQ и retry-очереди.

    Топология:
    - payments.events -> payments.new
    - payments.retry.N -> после TTL возвращаются в payments.events/payment.new
    - payments.dlx -> payments.new.dlq
    """
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )
    dlx = await channel.declare_exchange(
        DLX_EXCHANGE_NAME,
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    queue = await channel.declare_queue(
        QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE_NAME,
            "x-dead-letter-routing-key": DEAD_ROUTING_KEY,
        },
    )
    await queue.bind(exchange, routing_key=ROUTING_KEY)

    dlq = await channel.declare_queue(DLQ_NAME, durable=True)
    await dlq.bind(dlx, routing_key=DEAD_ROUTING_KEY)

    for delay_ms in RETRY_DELAYS_MS:
        retry_queue = await channel.declare_queue(
            retry_queue_name(delay_ms),
            durable=True,
            arguments={
                "x-message-ttl": delay_ms,
                "x-dead-letter-exchange": EXCHANGE_NAME,
                "x-dead-letter-routing-key": ROUTING_KEY,
            },
        )
        await retry_queue.bind(exchange, routing_key=retry_routing_key(delay_ms))

    return exchange