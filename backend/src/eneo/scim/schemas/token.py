from uuid import UUID

from pydantic import BaseModel, Field


class ScimTokenCreatedResponse(BaseModel):
    tenant_id: UUID
    token: str = Field(description="Plaintext token — shown once, never stored")


class ScimTokenStatusResponse(BaseModel):
    tenant_id: UUID
    is_active: bool
