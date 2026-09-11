from prometheus_client import Counter, Histogram

# HTTP-level metrics. `path` is the ROUTE TEMPLATE (e.g. /wallets/{wallet_id}),
# never the raw URL, so wallet UUIDs don't blow up label cardinality.
REQUESTS = Counter(
    "wallet_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "wallet_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Domain counters.
TRANSFERS_CREATED = Counter("wallet_transfers_created_total", "Transfers successfully applied")
TRANSFERS_DECLINED = Counter(
    "wallet_transfers_declined_insufficient_funds_total",
    "Transfers declined due to insufficient funds",
)
IDEMPOTENT_REPLAYS = Counter("wallet_idempotent_replays_total", "Idempotent transfer replays (same key, same body)")
TRANSFERS_CONFLICT = Counter(
    "wallet_transfers_conflict_total",
    "Transfers rejected: idempotency key reused with a different body",
)
DEPOSITS = Counter("wallet_deposits_total", "Deposits into wallets")
