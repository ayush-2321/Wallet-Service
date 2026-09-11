import json
import logging
import sys
from contextvars import ContextVar

# Correlation id for the in-flight request; set by the HTTP middleware and read
# by every log line emitted while handling that request (including in the sync
# route worker thread, since anyio copies the context into the threadpool).
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        payload = {
            "ts": f"{base}.{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": correlation_id.get(),
            "event": getattr(record, "event", record.getMessage()),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Our own `http_request` event replaces uvicorn's plain-text access log.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    logger.info(event, extra={"event": event, "fields": fields})
