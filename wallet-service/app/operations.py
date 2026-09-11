from uuid import UUID


def create_or_get_wallet(conn, user_id: UUID):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO wallets (user_id, balance_paise)
            VALUES (%s, 0)
            ON CONFLICT (user_id)
            DO UPDATE SET user_id = EXCLUDED.user_id
            RETURNING id, user_id, balance_paise
        """, (user_id,))
        return cur.fetchone()


def get_wallet(conn, wallet_id: UUID):
    with conn.cursor() as cur:
        cur.execute("SELECT id, user_id, balance_paise FROM wallets WHERE id = %s", (wallet_id,))
        return cur.fetchone()


def get_wallet_owner(conn, wallet_id: UUID):
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM wallets WHERE id = %s", (wallet_id,))
        row = cur.fetchone()
        return row[0] if row else None


def deposit(conn, wallet_id: UUID, user_id: UUID, amount_paise: int):
    # Ownership is enforced in the WHERE clause: you can only fund your own wallet.
    # A deposit is not a transfer, so it legitimately increases the system total.
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE wallets
            SET balance_paise = balance_paise + %s
            WHERE id = %s AND user_id = %s
            RETURNING balance_paise
        """, (amount_paise, wallet_id, user_id))
        row = cur.fetchone()
        return row[0] if row else None


def claim_idempotency_key(conn, idempotency_key, from_wallet, to_wallet, amount_paise):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO transfers (idempotency_key, from_wallet, to_wallet, amount_paise, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """, (idempotency_key, from_wallet, to_wallet, amount_paise))
        return cur.fetchone()


def get_transfer_by_key(conn, idempotency_key):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, idempotency_key, from_wallet, to_wallet, amount_paise, status, created_at
            FROM transfers WHERE idempotency_key = %s
        """, (idempotency_key,))
        return cur.fetchone()


def execute_transfer(conn, transfer_id, from_wallet, to_wallet, amount_paise) -> str:
    """Attempt the transfer inside the caller's transaction. Returns 'SUCCESS' or
    'FAILED'. On decline the transfer row is marked FAILED and NO balance is
    touched, but the caller COMMITS anyway so the declined transfer and its
    idempotency key persist (a retry replays the same decline)."""
    with conn.cursor() as cur:
        # Lock both rows in a fixed id order so opposite-direction transfers
        # (A->B and B->A) can never deadlock on lock-acquisition order.
        cur.execute("""
            SELECT id FROM wallets
            WHERE id IN (%s, %s) ORDER BY id FOR UPDATE
        """, (from_wallet, to_wallet))
        if len(cur.fetchall()) != 2:
            raise ValueError("One or both wallets do not exist")

        # Conditional debit: fails cleanly (0 rows) instead of going negative.
        cur.execute("""
            UPDATE wallets
            SET balance_paise = balance_paise - %s
            WHERE id = %s AND balance_paise >= %s
        """, (amount_paise, from_wallet, amount_paise))
        if cur.rowcount != 1:
            cur.execute("UPDATE transfers SET status = 'FAILED' WHERE id = %s", (transfer_id,))
            return "FAILED"

        cur.execute("UPDATE wallets SET balance_paise = balance_paise + %s WHERE id = %s", (amount_paise, to_wallet))
        cur.execute("UPDATE transfers SET status = 'SUCCESS' WHERE id = %s", (transfer_id,))
        return "SUCCESS"


def get_transfer(conn, transfer_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, idempotency_key, from_wallet, to_wallet, amount_paise, status, created_at
            FROM transfers WHERE id = %s
        """, (transfer_id,))
        return cur.fetchone()
