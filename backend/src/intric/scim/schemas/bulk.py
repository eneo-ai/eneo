from typing import Any

from pydantic import BaseModel


class BulkOperation(BaseModel):
    method: str
    path: str
    bulkId: str | None = None
    data: Any = None


class BulkRequest(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"]
    failOnErrors: int | None = None
    Operations: list[BulkOperation]


class BulkOperationResponse(BaseModel):
    method: str
    bulkId: str | None = None
    location: str | None = None
    status: str
    response: Any = None


class BulkResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:BulkResponse"]
    Operations: list[BulkOperationResponse]
