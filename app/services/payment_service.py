from __future__ import annotations
import logging
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import OutboxMessage, Payment, PaymentStatus
from app.schemas.payment import PaymentCreate

logger = logging.getLogger(__name__)

def _same_request(payment: Payment, data: PaymentCreate) -> bool:
    return (
        payment.amount == data.amount and payment.currency == data.currency
        and payment.description == data.description and payment.meta == data.metadata
        and str(payment.webhook_url) == str(data.webhook_url)
    )

async def create_payment(db: AsyncSession, data: PaymentCreate, idempotency_key: str) -> Payment:
    existing = await db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
    if existing is not None:
        if not _same_request(existing, data):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key already used for a different request")
        return existing

    payment = Payment(
        amount=data.amount, currency=data.currency, description=data.description,
        meta=data.metadata, idempotency_key=idempotency_key,
        webhook_url=str(data.webhook_url), status=PaymentStatus.pending,
    )
    db.add(payment)
    await db.flush()

    outbox = OutboxMessage(
        event_type="payment.created", aggregate_id=str(payment.id),
        payload={"event": "payment.created", "payment_id": str(payment.id), "idempotency_key": payment.idempotency_key},
    )
    db.add(outbox)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            if not _same_request(existing, data):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key already used for a different request")
            return existing
        raise

    await db.refresh(payment)
    return payment
