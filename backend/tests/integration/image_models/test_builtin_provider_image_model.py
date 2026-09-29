"""Built-in capability providers run on a catalog image model.

The provider row references the model through a real FK, the database
refuses an internal row without one, and the ask-time loader projects the
model (with its provider and classification) onto the provider entity.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.mcp_servers.application.capability_resolver import (
    get_active_capability_servers,
)


async def _internal_row(session, tenant_id, **columns) -> MCPServers:
    server = MCPServers(
        tenant_id=tenant_id,
        name=columns.pop("name", "Built-in images"),
        purpose="image_generation",
        http_url="http://localhost:8123/internal-mcp/image_generation/mcp",
        http_auth_type="internal",
        is_enabled=columns.pop("is_enabled", True),
        **columns,
    )
    session.add(server)
    await session.flush()
    return server


class TestSchemaInvariants:
    async def test_internal_row_requires_an_image_model(self, db_container, admin_user):
        async with db_container() as container:
            session = container.session()
            with pytest.raises(IntegrityError, match="ck_mcp_servers_internal"):
                await _internal_row(session, admin_user.tenant_id)

    async def test_internal_row_carries_no_own_classification(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "classified")
            classification = SecurityClassification(
                tenant_id=admin_user.tenant_id,
                name="Confidential",
                security_level=2,
            )
            session.add(classification)
            await session.flush()

            with pytest.raises(IntegrityError, match="no_classification"):
                await _internal_row(
                    session,
                    admin_user.tenant_id,
                    image_model_id=model.id,
                    security_classification_id=classification.id,
                )


class TestAskTimeProjection:
    async def test_active_provider_carries_its_backing_model(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            classification = SecurityClassification(
                tenant_id=admin_user.tenant_id,
                name="Internal",
                security_level=1,
            )
            session.add(classification)
            await session.flush()
            model = await image_model_factory(
                session,
                "gpt-image-1",
                nickname="GPT Image",
                security_classification_id=classification.id,
            )
            await _internal_row(session, admin_user.tenant_id, image_model_id=model.id)

            providers = await get_active_capability_servers(
                session, admin_user.tenant_id, "image_generation"
            )

            [provider] = providers
            assert provider.image_model_id == model.id
            assert provider.image_model is not None
            assert provider.image_model.nickname == "GPT Image"
            assert provider.image_model.name == "gpt-image-1"
            assert (provider.image_model.provider_name or "").lower() == "openai"
            assert provider.image_model.is_enabled is True
            assert provider.security_classification is None
            effective = provider.effective_security_classification
            assert effective is not None and effective.id == classification.id
            assert provider.is_backing_model_available is True

    async def test_disabled_backing_model_marks_provider_unavailable(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "off", is_enabled=False)
            await _internal_row(session, admin_user.tenant_id, image_model_id=model.id)

            [provider] = await get_active_capability_servers(
                session, admin_user.tenant_id, "image_generation"
            )

            assert provider.is_backing_model_available is False

    async def test_model_delete_is_refused_by_the_fk_as_last_resort(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "pinned")
            await _internal_row(session, admin_user.tenant_id, image_model_id=model.id)

            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.delete(model)
                    await session.flush()

            assert (
                await session.execute(
                    select(MCPServers.id).where(MCPServers.image_model_id == model.id)
                )
            ).scalar_one_or_none() is not None
