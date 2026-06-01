import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Union

from typing_extensions import override

from intric.main.config import get_loglevel
from intric.main.request_context import get_request_context

JSON_LOGS_ENABLED = os.getenv("JSON_LOGS", "true").lower() in {"1", "true", "yes", "on"}

# Resource block — read once at import time from env vars.
# Shared between the log formatter and the TracerProvider in observability.py.
_RESOURCE: dict[str, str] = {
    "service.name": os.getenv("OTEL_SERVICE_NAME", "eneo"),
    "service.version": os.getenv("OTEL_SERVICE_VERSION", "unknown"),
    # OTel semantic conventions ≥1.24: deployment.environment.name
    # Configured via OTEL_DEPLOYMENT_ENVIRONMENT env var.
    "deployment.environment.name": os.getenv(
        "OTEL_DEPLOYMENT_ENVIRONMENT", "production"
    ),
}

# OTel Logs Data Model severity_number mapping
# https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber
_SEVERITY_NUMBER: dict[str, int] = {
    "DEBUG": 5,
    "INFO": 9,
    "WARNING": 13,
    "WARN": 13,
    "ERROR": 17,
    "CRITICAL": 21,
    "FATAL": 21,
}

# Request context keys emitted as top-level fields (not moved into attributes)
_TOP_LEVEL_CONTEXT_KEYS = frozenset({"trace_id"})


def _get_span_context() -> dict[str, str]:
    """Return trace_id, span_id, trace_flags from the currently active OTEL span.

    Returns an empty dict when no span is active or the SDK is not initialised.
    Safe to call before init_observability() — the no-op span returns is_valid=False.
    """
    try:
        from opentelemetry import trace as _otel_trace

        span = _otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            return {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
                "trace_flags": format(int(ctx.trace_flags), "02x"),
            }
    except Exception:
        # Runs inside the logging formatter — any uncaught exception here
        # would propagate into logging.Handler.handleError and risk losing
        # log records. Trace correlation is best-effort; absence is fine.
        pass
    return {}


class OTELJSONFormatter(logging.Formatter):
    """Serialize log records as NDJSON mapped against the OTel Logs Data Model.

    Top-level fields: timestamp, severity_text, severity_number, body,
    trace_id, span_id, trace_flags, resource, attributes.

    All request context values and logger.extra fields land in ``attributes``.
    """

    RESERVED_ATTRS = frozenset(
        {
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
    )

    @override
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover
        severity_text = record.levelname.upper()

        log: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "severity_text": severity_text,
            "severity_number": _SEVERITY_NUMBER.get(severity_text, 9),
            "body": record.getMessage(),
        }

        # Inject trace correlation from the active OTEL span
        log.update(_get_span_context())

        # Build attributes from per-request context stored in contextvars.
        # trace_id is a top-level field (see _TOP_LEVEL_CONTEXT_KEYS) and is kept
        # out of attributes; fall back to the context value when no active span
        # produced one so the id is never silently dropped.
        context = get_request_context()
        if "trace_id" not in log and context.get("trace_id"):
            log["trace_id"] = context["trace_id"]
        attributes: dict[str, Any] = {}
        for key, value in context.items():
            if value is not None and key not in _TOP_LEVEL_CONTEXT_KEYS:
                attributes[key] = value

        # Merge extra fields passed via logger(..., extra={...})
        for key, value in record.__dict__.items():
            if key in self.RESERVED_ATTRS or key.startswith("_"):
                continue
            if value is None:
                continue
            attributes.setdefault(key, value)

        # Logger name is useful for tracing log origin
        attributes.setdefault("logger", record.name)

        if record.exc_info:
            attributes["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            attributes["stack"] = record.stack_info

        if attributes:
            log["attributes"] = attributes

        log["resource"] = _RESOURCE

        return json.dumps(log, default=str)


# Backward-compat alias — existing code that references ContextJSONFormatter still works
ContextJSONFormatter = OTELJSONFormatter


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
    FORMAT_STRING = "%(asctime)s | %(levelname)s | %(name)s : %(message)s"
    ERROR = logging.ERROR
    WARN = logging.WARN
    INFO = logging.INFO
    DEBUG = logging.DEBUG

    def __init__(
        self,
        name: str = "main",
        fmt_string: str = FORMAT_STRING,
        level: int = logging.WARNING,
        console: bool = True,
        files: Union[list[str], str, None] = None,
    ) -> None:
        logging.Logger.__init__(self, name, level)
        formatter_obj: logging.Formatter
        if JSON_LOGS_ENABLED:
            formatter_obj = OTELJSONFormatter()
        else:
            formatter_obj = logging.Formatter(fmt_string)

        file_list: list[str]
        if files is None:
            file_list = []
        elif isinstance(files, str):
            file_list = [files]
        else:
            file_list = files

        def _add_stream(handler_cls: type[logging.Handler], **kwargs: object) -> None:
            handler = handler_cls(**kwargs)  # type: ignore[call-arg]  # dynamic kwargs forwarded to Handler subclass
            handler.setLevel(level)
            handler.setFormatter(formatter_obj)
            self.addHandler(handler)

        if console is True:
            _add_stream(logging.StreamHandler, stream=sys.stdout)

        for filepath in file_list:
            _add_stream(logging.FileHandler, filename=filepath)


def get_logger(module_name: str):
    # If we don't add a handler manually one will be created for us
    return SimpleLogger(name=module_name, level=get_loglevel())
