import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_session
from app.models import Outbox, Payment, PaymentStatus
from app.schemas import PaymentCreate, PaymentCreated, PaymentDetail

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreated,
)
async def create_payment(
    body: PaymentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1),
    session: AsyncSession = Depends(get_session),
) -> PaymentCreated:
    # Идемпотентность: если такой ключ уже есть — возвращаем существующий платёж
    existing = await session.scalar(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    if existing:
        return PaymentCreated(
            payment_id=existing.id,
            status=existing.status,
            created_at=existing.created_at,
        )

    payment = Payment(
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        payment_metadata=body.metadata,
        webhook_url=str(body.webhook_url),
        idempotency_key=idempotency_key,
        status=PaymentStatus.PENDING,
    )
    session.add(payment)
    try:
        await session.flush()  # получаем payment.id
    except IntegrityError:
        # гонка: параллельный запрос с тем же ключом уже вставил
        await session.rollback()
        existing = await session.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing:
            return PaymentCreated(
                payment_id=existing.id,
                status=existing.status,
                created_at=existing.created_at,
            )
        raise

    # Outbox: событие кладём в ту же транзакцию
    session.add(
        Outbox(
            event_type="payment.new",
            payload={"payment_id": str(payment.id)},
        )
    )

    await session.commit()
    await session.refresh(payment)

    return PaymentCreated(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get("/{payment_id}", response_model=PaymentDetail)
async def get_payment(
    payment_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment