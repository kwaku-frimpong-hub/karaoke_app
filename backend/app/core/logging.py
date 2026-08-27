"""Structured logging setup.

Emits single-line JSON log records to stdout so logs are machine-parseable
(useful for the Dockerized deployment later, M20). Configured at application
startup via :func:`setup_logging`.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(settings: Settings) -> None:
    """Configure the root and uvicorn loggers to emit JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(handlers=[handler], level=settings.log_level, force=True)

    # Route uvicorn's own loggers through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(settings.log_level)

    # SQLAlchemy emits SQL statements at INFO level; keep the console quiet.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
