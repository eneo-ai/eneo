from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException
from intric.settings.metadata_fields import MetadataFieldType, TenantMetadataFieldInDB
from intric.settings.tenant_metadata_field_service import TenantMetadataFieldService


def _build_service(fields: list[TenantMetadataFieldInDB]) -> TenantMetadataFieldService:
    return TenantMetadataFieldService(
        user=SimpleNamespace(tenant_id=uuid4()),
        repo=SimpleNamespace(list_by_tenant=AsyncMock(return_value=fields)),
    )


@pytest.mark.asyncio
async def test_validate_metadata_allows_matching_tenant_field_types():
    field = TenantMetadataFieldInDB(
        id=uuid4(),
        tenant_id=uuid4(),
        name="case_id",
        field_type=MetadataFieldType.INT,
        visible_on_assistants=True,
        visible_on_spaces=False,
    )
    service = _build_service([field])

    await service.validate_metadata_for_resource(
        {
            "eneo": [
                {"key": "case_id", "value": 42, "type": "int"},
                {"key": "custom_key", "value": {"nested": "allowed"}, "type": "string"},
            ]
        },
        resource_type="assistant",
    )


@pytest.mark.asyncio
async def test_validate_metadata_rejects_hidden_tenant_field_on_space():
    field = TenantMetadataFieldInDB(
        id=uuid4(),
        tenant_id=uuid4(),
        name="case_id",
        field_type=MetadataFieldType.INT,
        visible_on_assistants=True,
        visible_on_spaces=False,
    )
    service = _build_service([field])

    with pytest.raises(BadRequestException, match="not available on spaces"):
        await service.validate_metadata_for_resource(
            {"eneo": [{"key": "case_id", "value": 42, "type": "int"}]},
            resource_type="space",
        )


@pytest.mark.asyncio
async def test_validate_metadata_rejects_wrong_tenant_field_type():
    field = TenantMetadataFieldInDB(
        id=uuid4(),
        tenant_id=uuid4(),
        name="is_published",
        field_type=MetadataFieldType.BOOLEAN,
        visible_on_assistants=True,
        visible_on_spaces=True,
    )
    service = _build_service([field])

    with pytest.raises(BadRequestException, match="must be of type boolean"):
        await service.validate_metadata_for_resource(
            {"eneo": [{"key": "is_published", "value": "true", "type": "boolean"}]},
            resource_type="assistant",
        )


@pytest.mark.asyncio
async def test_validate_metadata_rejects_declared_type_mismatch():
    field = TenantMetadataFieldInDB(
        id=uuid4(),
        tenant_id=uuid4(),
        name="case_id",
        field_type=MetadataFieldType.INT,
        visible_on_assistants=True,
        visible_on_spaces=True,
    )
    service = _build_service([field])

    with pytest.raises(BadRequestException, match="must declare type int"):
        await service.validate_metadata_for_resource(
            {"eneo": [{"key": "case_id", "value": 42, "type": "string"}]},
            resource_type="assistant",
        )
