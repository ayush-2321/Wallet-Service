import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_user
from app.db import get_connection
from app.logging_setup import get_logger, log_event
from app.metrics import DEPOSITS
from app.operations import create_or_get_wallet, deposit, get_wallet

router = APIRouter(prefix="/wallets", tags=["wallets"])
log = get_logger("wallet.wallets")


class DepositRequest(BaseModel):
    amount_paise: int = Field(gt=0)


@router.post("")
def create_wallet(user_id: uuid.UUID = Depends(require_user)):
    with get_connection() as conn:
        wallet = create_or_get_wallet(conn, user_id)
    log_event(log, "wallet_get_or_create", wallet_id=str(wallet[0]), user_id=str(user_id), balance_paise=wallet[2])
    return {"wallet_id": str(wallet[0]), "user_id": str(wallet[1]), "balance_paise": wallet[2]}


@router.get("/{wallet_id}")
def read_wallet(wallet_id: uuid.UUID, _: uuid.UUID = Depends(require_user)):
    with get_connection() as conn:
        wallet = get_wallet(conn, wallet_id)
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"wallet_id": str(wallet[0]), "user_id": str(wallet[1]), "balance_paise": wallet[2]}


@router.post("/{wallet_id}/deposit")
def deposit_to_wallet(wallet_id: uuid.UUID, request: DepositRequest, user_id: uuid.UUID = Depends(require_user)):
    with get_connection() as conn:
        with conn.transaction():
            balance = deposit(conn, wallet_id, user_id, request.amount_paise)
    if balance is None:
        raise HTTPException(status_code=404, detail="Wallet not found or not owned by caller")
    DEPOSITS.inc()
    log_event(log, "wallet_deposited", wallet_id=str(wallet_id), amount_paise=request.amount_paise, balance_paise=balance)
    return {"wallet_id": str(wallet_id), "balance_paise": balance}
