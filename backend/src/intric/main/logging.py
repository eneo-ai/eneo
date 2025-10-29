import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from rich.logging import RichHandler

from intric.main.config import get_loglevel
from intric.main.request_context import get_request_context


JSON_LOGS_ENABLED = os.getenv("JSON_LOGS", "true").lower() in {"1", "true", "yes", "on"}


class ContextJSONFormatter(logging.Formatter):
    """Serialize log records with request context into JSON."""

    RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
    }

    DEFAULT_KEYS = ("correlation_id", "tenant_slug", "user_email", "error_code", "status_code")

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting logic
        log: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach request context values (correlation, tenant, etc.)
        for key, value in get_request_context().items():
            if value is not None and key not in log:
                log[key] = value

        # Include extra attributes passed via logger(..., extra={})
        for key, value in record.__dict__.items():
            if key in self.RESERVED_ATTRS or key.startswith("_"):
                continue
            if value is None:
                continue
            log.setdefault(key, value)

        # Ensure important keys exist even if None
        for key in self.DEFAULT_KEYS:
            if key not in log and getattr(record, key, None) is not None:
                log[key] = getattr(record, key)

        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            log["stack"] = record.stack_info

        return json.dumps(log, default=str)

# Disable loggers from other packages if loglevel is INFO or above
for _logger in logging.root.manager.loggerDict:
    if get_loglevel() <= logging.DEBUG:
        logging.getLogger(_logger).setLevel(logging.INFO)
    else:
        logging.getLogger(_logger).setLevel(logging.CRITICAL)

# Always suppress SQLAlchemy loggers AFTER other logger configuration (too verbose for normal operation)
# Must override the loop above which may set them to INFO/CRITICAL
# Disable propagation to prevent logs from reaching root logger
sqlalchemy_loggers = [
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "sqlalchemy.orm",
    "sqlalchemy.dialects",
]
for logger_name in sqlalchemy_loggers:
    sa_logger = logging.getLogger(logger_name)
    sa_logger.setLevel(logging.WARNING)
    sa_logger.propagate = False  # Don't propagate to root logger


# noqa Copied from https://dev.to/taikedz/simple-python-logging-and-a-digression-on-dependencies-trust-and-copypasting-code-229o
class SimpleLogger(logging.Logger):
    FORMAT_STRING = '%(asctime)s | %(levelname)s | %(name)s : %(message)s'
    ERROR = logging.ERROR
    WARN = logging.WARN
    INFO = logging.INFO
    DEBUG = logging.DEBUG

    def __init__(
        self,
        name="main",
        fmt_string=FORMAT_STRING,
        level=logging.WARNING,
        console=True,
        files=None,
    ):
        logging.Logger.__init__(self, name, level)
        formatter_obj: logging.Formatter
        if JSON_LOGS_ENABLED:
            formatter_obj = ContextJSONFormatter()
        else:
            formatter_obj = logging.Formatter(fmt_string)

        if files is None:
            files = []
        elif isinstance(files, str):
            files = [files]

        def _add_stream(handler: logging.Handler, **kwargs):
            handler = handler(**kwargs)
            handler.setLevel(level)
            handler.setFormatter(formatter_obj)
            self.addHandler(handler)

        if console is True:
            if JSON_LOGS_ENABLED:
                _add_stream(logging.StreamHandler, stream=sys.stdout)
            else:
                # Use Rich for prettier console output when not using JSON logs
                rich_handler = RichHandler(rich_tracebacks=True, markup=True, show_path=True)
                rich_handler.setLevel(level)
                # RichHandler has its own formatting, so only use custom formatter for JSON
                self.addHandler(rich_handler)

        for filepath in files:
            _add_stream(logging.FileHandler, filename=filepath)


def get_logger(module_name: str):
    # If we don't add a handler manually one will be created for us
    return SimpleLogger(name=module_name, level=get_loglevel())
