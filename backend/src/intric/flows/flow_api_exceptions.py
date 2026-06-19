from __future__ import annotations

from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.main.exceptions import BadRequestException


class FlowBadRequestException(BadRequestException):
    """Flow bad-request exception with code narrowed to FlowApiErrorCode."""

    code: FlowApiErrorCode

    def __init__(
        self,
        message: str = "",
        *,
        code: FlowApiErrorCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code
