import os
import time
from pathlib import Path

from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/wallet")
pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection():
    return pool.connection()


def init_schema(retries: int = 10, delay: float = 2.0) -> None:
    """Apply schema.sql on startup. Idempotent (CREATE ... IF NOT EXISTS), so it's
    safe to run every boot. Retries because a freshly-provisioned managed Postgres
    may not accept connections the instant the app starts."""
    statements = [s.strip() for s in SCHEMA_PATH.read_text().split(";") if s.strip()]
    last_exc = None
    for _ in range(retries):
        try:
            with pool.connection() as conn, conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            return
        except Exception as exc:  # DB not ready yet — wait and retry
            last_exc = exc
            time.sleep(delay)
    raise RuntimeError(f"Could not initialise schema after {retries} attempts") from last_exc
