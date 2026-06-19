from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from intric.flows.http_transport.authored_config import HttpMethod


class HttpRequestPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    url: str
    headers: dict[str, str]
    body_preview: str | None
