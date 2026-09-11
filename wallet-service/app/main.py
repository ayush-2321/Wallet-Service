import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.db import init_schema
from app.logging_setup import configure_logging, correlation_id, get_logger, log_event
from app.metrics import LATENCY, REQUESTS
from app.transfers import router as transfer_router
from app.wallets import router as wallet_router

configure_logging()
log = get_logger("wallet.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()  # create tables if missing (safe on every boot)
    log_event(log, "startup_complete")
    yield


app = FastAPI(title="Wallet Service", version="1.0.0", lifespan=lifespan)
app.include_router(wallet_router)
app.include_router(transfer_router)


def _route_path(request: Request) -> str:
    # The matched route template (/wallets/{wallet_id}), not the raw URL, so ids
    # don't explode metric label cardinality. Falls back to raw path on 404.
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


@app.middleware("http")
async def observability(request: Request, call_next):
    cid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = correlation_id.set(cid)
    start = time.perf_counter()
    status_code = 500  # if call_next raises, this is what we record
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = cid
        return response
    finally:
        duration = time.perf_counter() - start
        path = _route_path(request)
        LATENCY.labels(request.method, path).observe(duration)
        REQUESTS.labels(request.method, path, str(status_code)).inc()
        log_event(
            log, "http_request", method=request.method, path=path,
            status=status_code, duration_ms=round(duration * 1000, 2),
        )
        correlation_id.reset(token)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
