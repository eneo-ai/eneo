from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.config import JsonDict

from eneo.flows.http_transport import (
    HttpAuthoredConfig,
    HttpMethod,
    HttpRequestPreview,
    HttpTransportError,
)

HTTP_TEST_REQUEST_EXAMPLE: JsonDict = {
    "step_id": "e0388e4a-699d-43d9-a216-43c3f50b9be3",
    "direction": "output",
    "method": "POST",
    "config": {
        "url": "{{base_url}}/eneo/{{name}}",
        "auth": {"mode": "none"},
        "timeout_seconds": 10,
        "body": {
            "mode": "json_template",
            "template": '{"event":"flow.test","case_id":"{{flow_input.case_id}}"}',
        },
        "custom_headers": [
            {"name": "X-Eneo-Test", "value": "{{name}}", "secret": False}
        ],
        "response_format": "json",
    },
    "test_variables": {
        "base_url": "https://webhook.example.com",
        "name": "alex",
        "flow_input": {"case_id": "CASE-1"},
    },
}

HTTP_TEST_RESPONSE_EXAMPLE: JsonDict = {
    "success": True,
    "status_code": 200,
    "duration_ms": 128.4,
    "response_preview": '{"ok":true}',
    "request_preview": {
        "method": "POST",
        "url": "https://webhook.example.com/eneo/alex",
        "headers": {"X-Eneo-Test": "alex"},
        "body_preview": '{"event": "flow.test", "case_id": "CASE-1"}',
    },
    "error_code": None,
    "error_message": None,
}


class HttpTestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": HTTP_TEST_REQUEST_EXAMPLE},
    )

    step_id: UUID
    config: HttpAuthoredConfig
    direction: Literal["input", "output"] = "output"
    method: HttpMethod = "POST"
    test_variables: dict[str, Any] | None = None


class HttpTestResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": HTTP_TEST_RESPONSE_EXAMPLE})

    success: bool
    status_code: int | None = None
    duration_ms: float = 0.0
    response_preview: str | None = None
    request_preview: HttpRequestPreview | None = None
    error_code: HttpTransportError | None = None
    error_message: str | None = None
