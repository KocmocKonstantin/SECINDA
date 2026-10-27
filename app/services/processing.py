import asyncio
import logging
import random
from datetime import datetime, timezone
from uuid import UUID
import httpx
from sqlalchemy import update
from app.config import settings
from app.db.models import Payment, PaymentStatus
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

class WebhookDeliveryError(Exception):
    pass

async def emulate_payment_gateway() -> bool:
    await asyncio.sleep(random.uniform(2.0, 5.0))
    return random.random() < 0.9

def build_webhook_payload(payment: Payment) -> dict:
    return {
        "event": "payment.processed", "payment_id": str(payment.id),
        "idempotency_key": payment.idempotency_key, "status": payment.status.value,
        "amount": str(payment.amount), "currency": payment.currency.value,
        "description": payment.description, "metadata": payment.meta,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
    }

async def deliver_webhook(payment: Payment) -> None:
    payload = build_webhook_payload(payment)
    delays = [1, 2, 4]
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
        for attempt in range(3):
            try:
                response = await client.post(str(payment.webhook_url), json=payload)
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code < 500 and exc.response.status_code not in (408, 429):
                    logger.warning("Webhook returned client error %s, not retrying", exc.response.status_code)
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt < 2:
                await asyncio.sleep(delays[attempt])
    raise WebhookDeliveryError(f"Webhook delivery failed after 3 attempts: {last_error}")

async def process_payment_event(event: dict) -> None:
    payment_id = UUID(str(event["payment_id"]))
    async with SessionLocal() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            logger.warning("Payment %s not found, skipping event", payment_id)
            return
        if payment.status == PaymentStatus.pending:
            success = await emulate_payment_gateway()
            new_status = PaymentStatus.succeeded if success else PaymentStatus.failed
            result = await session.execute(
                update(Payment).where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
                .values(status=new_status, processed_at=datetime.now(timezone.utc))
            )
            await session.commit()
            payment = await session.get(Payment, payment_id)
            if payment is None:
                return
            if result.rowcount == 0:
                logger.info("Payment %s was processed concurrently, using current state", payment_id)
        if payment.status != PaymentStatus.pending and payment.webhook_sent_at is None:
            await deliver_webhook(payment)
            await session.execute(
                update(Payment).where(Payment.id == payment_id, Payment.webhook_sent_at.is_(None))
                .values(webhook_sent_at=datetime.now(timezone.utc))
            )
            await session.commit()
