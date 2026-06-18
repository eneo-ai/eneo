from typing import Literal, TypedDict, cast
from uuid import UUID

from intric.main.exceptions import BadRequestException
from intric.roles.permissions import Permission, validate_permissions
from intric.settings.metadata_fields import (
    MetadataFieldType,
    TenantMetadataFieldCreate,
    TenantMetadataFieldPublic,
    TenantMetadataFieldUpdate,
)
from intric.settings.tenant_metadata_field_repo import TenantMetadataFieldRepository
from intric.users.user import UserInDB

ResourceType = Literal["assistant", "space"]
MetadataFieldTypeValue = Literal["int", "string", "boolean"]


class MetadataEntry(TypedDict):
    key: str
    value: object
    type: MetadataFieldTypeValue


class TenantMetadataFieldService:
    def __init__(self, user: UserInDB, repo: TenantMetadataFieldRepository):
        self.user = user
        self.repo = repo

    async def list_fields(self) -> list[TenantMetadataFieldPublic]:
        fields = await self.repo.list_by_tenant(self.user.tenant_id)
        return [TenantMetadataFieldPublic.model_validate(field) for field in fields]

    @validate_permissions(Permission.ADMIN)
    async def create_field(
        self, metadata_field: TenantMetadataFieldCreate
    ) -> TenantMetadataFieldPublic:
        field = await self.repo.add(self.user.tenant_id, metadata_field)
        return TenantMetadataFieldPublic.model_validate(field)

    @validate_permissions(Permission.ADMIN)
    async def update_field(
        self, metadata_field: TenantMetadataFieldUpdate
    ) -> TenantMetadataFieldPublic:
        field = await self.repo.update(self.user.tenant_id, metadata_field)
        return TenantMetadataFieldPublic.model_validate(field)

    @validate_permissions(Permission.ADMIN)
    async def delete_field(self, field_id: UUID) -> None:
        await self.repo.delete(self.user.tenant_id, field_id)

    async def validate_metadata_for_resource(
        self,
        metadata_json: dict[str, object] | None,
        *,
        resource_type: ResourceType,
    ) -> None:
        if metadata_json is None:
            return

        metadata_fields = await self.repo.list_by_tenant(self.user.tenant_id)
        fields_by_name = {field.name: field for field in metadata_fields}
        visibility_attr = (
            "visible_on_assistants"
            if resource_type == "assistant"
            else "visible_on_spaces"
        )

        for entry in self._extract_eneo_entries(metadata_json):
            key = entry["key"]
            value = entry["value"]
            field_type = entry["type"]

            metadata_field = fields_by_name.get(key)
            if metadata_field is None:
                continue

            if not getattr(metadata_field, visibility_attr):
                raise BadRequestException(
                    f"Metadata field '{key}' is not available on {resource_type}s."
                )

            if field_type != metadata_field.field_type.value:
                raise BadRequestException(
                    f"Metadata field '{key}' must declare type {metadata_field.field_type.value}."
                )

            if not self._matches_field_type(value, metadata_field.field_type):
                raise BadRequestException(
                    f"Metadata field '{key}' must be of type {metadata_field.field_type.value}."
                )

    @staticmethod
    def _extract_eneo_entries(metadata_json: dict[str, object]) -> list[MetadataEntry]:
        eneo = metadata_json.get("eneo")
        if not isinstance(eneo, list):
            return []
        eneo_entries = cast(list[object], eneo)

        entries: list[MetadataEntry] = []
        for entry in eneo_entries:
            if not isinstance(entry, dict):
                continue

            entry_dict = cast(dict[str, object], entry)
            key = entry_dict.get("key")
            field_type = entry_dict.get("type")
            if not isinstance(key, str) or field_type not in {
                MetadataFieldType.STRING.value,
                MetadataFieldType.INT.value,
                MetadataFieldType.BOOLEAN.value,
            }:
                continue

            entries.append(
                {
                    "key": key,
                    "type": cast(MetadataFieldTypeValue, field_type),
                    "value": entry_dict.get("value"),
                }
            )

        return entries

    @staticmethod
    def _matches_field_type(value: object, field_type: MetadataFieldType) -> bool:
        if field_type == MetadataFieldType.BOOLEAN:
            return isinstance(value, bool)
        if field_type == MetadataFieldType.STRING:
            return isinstance(value, str)
        if field_type == MetadataFieldType.INT:
            return isinstance(value, int) and not isinstance(value, bool)
        return False
