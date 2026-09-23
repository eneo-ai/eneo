"""The run contract carries the security classification of the flow's space,
so a runner can show what information the flow may take."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from tests.integration.module_session_support import (
    enable_module,
    install_module,
    module_login,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CLASSIFICATION = {
    "name": "Känslig",
    "description": "Personuppgifter får behandlas.",
    "security_level": 2,
}


@dataclass(frozen=True)
class PublishedFlow:
    admin_token: str
    tenant_id: UUID
    space_id: UUID
    run_contract_path: str

    @property
    def admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_token}"}


@pytest.fixture
async def published(
    client,
    db_container,
    admin_user,
    flow_process_auth_headers,
    create_published_compose_text_flow,
) -> PublishedFlow:
    flow = await create_published_compose_text_flow(client, flow_process_auth_headers)
    async with db_container() as container:
        stored = await container.flow_repo().get(
            UUID(flow.flow_id), admin_user.tenant_id
        )
    return PublishedFlow(
        admin_token=flow_process_auth_headers.token,
        tenant_id=admin_user.tenant_id,
        space_id=stored.space_id,
        run_contract_path=f"/api/v1/flows/{flow.flow_id}/run-contract/",
    )


async def _classify(
    db_container, published: PublishedFlow, *, classifications_on: bool
) -> None:
    async with db_container() as container:
        session = container.session()
        classification = SecurityClassifications(
            tenant_id=published.tenant_id, **CLASSIFICATION
        )
        session.add(classification)
        await session.flush()
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == published.space_id)
            .values(security_classification_id=classification.id)
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == published.tenant_id)
            .values(security_enabled=classifications_on)
        )


async def _classification(
    client: AsyncClient, published: PublishedFlow, headers: Mapping[str, str]
) -> Any:
    response = await client.get(published.run_contract_path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["security_classification"]


async def test_a_classified_spaces_flow_carries_its_classification(
    client: AsyncClient, published: PublishedFlow, db_container
):
    await _classify(db_container, published, classifications_on=True)

    assert await _classification(client, published, published.admin_headers) == (
        CLASSIFICATION
    )


async def test_an_unclassified_space_gives_null(
    client: AsyncClient, published: PublishedFlow, db_container
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == published.tenant_id)
            .values(security_enabled=True)
        )

    assert await _classification(client, published, published.admin_headers) is None


async def test_turned_off_classifications_give_null(
    client: AsyncClient, published: PublishedFlow, db_container
):
    await _classify(db_container, published, classifications_on=False)

    assert await _classification(client, published, published.admin_headers) is None


async def test_a_module_session_sees_the_same_classification(
    client: AsyncClient, published: PublishedFlow, db_container
):
    await _classify(db_container, published, classifications_on=True)
    module_key = await enable_module(db_container, tenant_id=published.tenant_id)
    secret = await install_module(
        client, admin_token=published.admin_token, module_key=module_key
    )
    module_token = await module_login(
        client,
        service_key=secret,
        user_token=published.admin_token,
        module_key=module_key,
    )
    headers = {"X-API-Key": secret, "Authorization": f"Bearer {module_token}"}

    assert await _classification(client, published, headers) == CLASSIFICATION
