"""The 429 every run-creating route returns when the run limit is reached."""

from __future__ import annotations

from typing import Final

from fastapi import Request, status
from fastapi.responses import JSONResponse

from eneo.flows.domain.flow_run_exceptions import FlowRunConcurrencyLimitReachedError
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.server.exception_handlers import extract_request_id

# A fixed hint: how long a run holds its slot is unknown at refusal time, so the
# value is not derived from the limit or the queue; clients poll the capacity route.
FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS: Final[int] = 60
FLOW_RUN_CONCURRENCY_MESSAGE: Final[str] = "Concurrent flow run limit reached."


def flow_run_concurrency_limit_response(
    request: Request, exc: FlowRunConcurrencyLimitReachedError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS)},
        content=GeneralError(
            message=FLOW_RUN_CONCURRENCY_MESSAGE,
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED.value,
            context={
                "max_concurrent_runs": exc.max_concurrent_runs,
                "retry_after_seconds": FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS,
            },
            request_id=extract_request_id(request),
        ).model_dump(mode="json", exclude_none=True),
    )
