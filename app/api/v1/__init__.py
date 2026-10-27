from fastapi import APIRouter, Depends
from app.api.v1 import payments
from app.security import require_api_key

api_router = APIRouter(dependencies=[Depends(require_api_key)])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
