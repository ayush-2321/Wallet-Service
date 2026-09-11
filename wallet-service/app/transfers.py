import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg.errors import ForeignKeyViolation
from pydantic import BaseModel, Field

from app.auth import require_user
from app.db import get_connection
from app.logging_setup import get_logger, log_event
from app.metrics import IDEMPOTENT_REPLAYS, TRANSFERS_CONFLICT, TRANSFERS_CREATED, TRANSFERS_DECLINED
from app.operations import (
    claim_idempotency_key,
    execute_transfer,
    get_transfer,
    get_transfer_by_key,
    get_wallet_owner,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])
log = get_logger("wallet.transfers")


class TransferRequest(BaseModel):
    from_wallet: uuid.UUID = Field(alias="from")
    to_wallet: uuid.UUID = Field(alias="to")
    amount_paise: int = Field(gt=0)


@router.post("")
def create_transfer(
    request: TransferRequest,
    caller: uuid.UUID = Depends(require_user),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    if request.from_wallet == request.to_wallet:
        raise HTTPException(status_code=400, detail="Source and destination wallets must be different")

    with get_connection() as conn:
        # A caller may only move money OUT OF a wallet they own.
        owner = get_wallet_owner(conn, request.from_wallet)
        if owner is None:
            raise HTTPException(status_code=404, detail="Source wallet not found")
        if owner != caller:
            raise HTTPException(status_code=403, detail="Caller does not own the source wallet")

        try:
            with conn.transaction():
                claimed = claim_idempotency_key(
                    conn, idempotency_key, request.from_wallet, request.to_wallet, request.amount_paise
                )
                if claimed is None:
                    # Key already exists: this is a retry (or a conflicting reuse).
                    existing = get_transfer_by_key(conn, idempotency_key)
                    same_request = (
                        existing[2] == request.from_wallet
                        and existing[3] == request.to_wallet
                        and existing[4] == request.amount_paise
                    )
                    if not same_request:
                        TRANSFERS_CONFLICT.inc()
                        log_event(log, "transfer_conflict", idempotency_key=idempotency_key)
                        raise HTTPException(status_code=409, detail="Idempotency key already used with a different request")
                    IDEMPOTENT_REPLAYS.inc()
                    log_event(log, "idempotent_replay", transfer_id=str(existing[0]), status=existing[5])
                    return {"transfer_id": str(existing[0]), "status": existing[5], "replayed": True}

                transfer_id = claimed[0]
                log_event(
                    log, "transfer_created", transfer_id=str(transfer_id),
                    from_wallet=str(request.from_wallet), to_wallet=str(request.to_wallet),
                    amount_paise=request.amount_paise,
                )
                status = execute_transfer(
                    conn, transfer_id, request.from_wallet, request.to_wallet, request.amount_paise
                )
                if status == "FAILED":
                    TRANSFERS_DECLINED.inc()
                    log_event(log, "transfer_declined", transfer_id=str(transfer_id), reason="insufficient_funds")
                    return {"transfer_id": str(transfer_id), "status": "FAILED", "reason": "insufficient_funds"}

                TRANSFERS_CREATED.inc()
                log_event(log, "transfer_debited", transfer_id=str(transfer_id), wallet_id=str(request.from_wallet), amount_paise=request.amount_paise)
                log_event(log, "transfer_credited", transfer_id=str(transfer_id), wallet_id=str(request.to_wallet), amount_paise=request.amount_paise)
                return {"transfer_id": str(transfer_id), "status": "SUCCESS"}
        except HTTPException:
            raise
        except ForeignKeyViolation:
            raise HTTPException(status_code=404, detail="One or both wallets do not exist")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{transfer_id}")
def read_transfer(transfer_id: uuid.UUID, _: uuid.UUID = Depends(require_user)):
    with get_connection() as conn:
        transfer = get_transfer(conn, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return {
        "transfer_id": str(transfer[0]),
        "idempotency_key": transfer[1],
        "from": str(transfer[2]),
        "to": str(transfer[3]),
        "amount_paise": transfer[4],
        "status": transfer[5],
        "created_at": transfer[6],
    }
