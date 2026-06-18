from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.main.models import InDB


class MetadataFieldType(str, Enum):
    INT = "int"
    STRING = "string"
    BOOLEAN = "boolean"


class TenantMetadataFieldBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    field_type: MetadataFieldType
    visible_on_assistants: bool = True
    visible_on_spaces: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Metadata field name can not be empty")
        return stripped


class TenantMetadataFieldCreate(TenantMetadataFieldBase):
    pass


class TenantMetadataFieldUpdate(TenantMetadataFieldBase):
    id: UUID


class TenantMetadataFieldInDB(TenantMetadataFieldBase, InDB):
    tenant_id: UUID
    model_config = ConfigDict(from_attributes=True)


class TenantMetadataFieldPublic(TenantMetadataFieldBase, InDB):
    tenant_id: UUID
    model_config = ConfigDict(from_attributes=True)
