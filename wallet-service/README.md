# Wallet Service

## Run locally with Docker

```bash
docker compose up --build
```

API: `http://localhost:8000`

Swagger UI: `http://localhost:8000/docs`

Metrics: `http://localhost:8000/metrics`

## Quick test

Create wallets:

```bash
curl -X POST 'http://localhost:8000/wallets?user_id=00000000-0000-0000-0000-000000000001'
curl -X POST 'http://localhost:8000/wallets?user_id=00000000-0000-0000-0000-000000000002'
```

For transfers, use the returned wallet IDs:

```bash
curl -X POST http://localhost:8000/transfers \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: test-001' \
  -d '{"from":"SOURCE_WALLET_ID","to":"DEST_WALLET_ID","amount_paise":100}'
```

Repeat the same request with the same idempotency key to test replay.

## Metrics

Prometheus text metrics are exposed at `/metrics`.

Included metrics:
- `wallet_http_requests_total`
- `wallet_http_request_duration_seconds` (use histogram buckets to calculate p99)
- `wallet_transfers_created_total`
- `wallet_transfers_declined_insufficient_funds_total`
- `wallet_idempotent_replays_total`

Note: the HTTP status middleware is intentionally small; for production-grade status accounting, instrument the response status directly in a single middleware.
