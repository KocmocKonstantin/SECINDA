from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Payment
from app.db.session import get_db
from app.schemas.payment import PaymentCreate, PaymentCreateResponse, PaymentRead
from app.services.payment_service import create_payment

router = APIRouter()

@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=PaymentCreateResponse)
async def create_payment_endpoint(
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
):
    idempotency_key = idempotency_key_header or payload.idempotency_key
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency key is required. Pass Idempotency-Key header or body field idempotency_key.",
        )
    payment = await create_payment(db, payload, idempotency_key)
    return PaymentCreateResponse(payment_id=payment.id, status=payment.status, created_at=payment.created_at)

@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment_endpoint(payment_id: UUID, db: AsyncSession = Depends(get_db)):
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment
