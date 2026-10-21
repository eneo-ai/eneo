"""The forecast model is a catalog model the Forecast source runs on.

Eneo gives a tenant the deployment's tool service as a provider and its
"default" checkpoint as a forecast model, once; the Forecast source references
the model through a real FK, follows its enablement and classification, and
the model is governed (on/off, classification, name) in one audited call.
"""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.ai_models_table import ForecastModels
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.forecast_models.application import forecast_model_provisioning
from eneo.forecast_models.application.forecast_model_provisioning import (
    ensure_default_forecast_model,
)
from eneo.main.models import ModelId
from eneo.mcp_servers.application.capability_resolver import (
    get_active_capability_servers,
)
from eneo.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)
from eneo.mcp_servers.application.runtime_status import RuntimeStatus
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module

TOOL_SERVICE = "eneo_tool_service"


async def _forecast_source(session, tenant_id, forecast_model_id, **columns):
    server = MCPServers(
        tenant_id=tenant_id,
        name=columns.pop("name", "Forecast"),
        purpose="forecast",
        http_url="http://tool-runtime:3010/mcp/forecast",
        http_auth_type="bundled",
        forecast_model_id=forecast_model_id,
        is_enabled=columns.pop("is_enabled", True),
        **columns,
    )
    session.add(server)
    await session.flush()
    return server


async def _classification(session, tenant_id, name="Internal", level=1):
    classification = SecurityClassification(
        tenant_id=tenant_id, name=name, security_level=level
    )
    session.add(classification)
    await session.flush()
    return classification


@pytest.fixture
def headers(admin_user_api_key):
    return {"X-API-Key": admin_user_api_key.key}


@pytest.fixture(autouse=True)
def runtime_reports_no_names(monkeypatch):
    """Whatever tool runtime the environment runs, it reports no model names."""
    monkeypatch.setattr(
        forecast_model_provisioning,
        "runtime_status",
        AsyncMock(return_value=RuntimeStatus(expected_version="test")),
    )


class TestProvisioning:
    async def test_a_tenant_gets_the_tool_service_and_its_default_model_once(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            first = await ensure_default_forecast_model(session, admin_user.tenant_id)
            second = await ensure_default_forecast_model(session, admin_user.tenant_id)

            assert first == second
            model = await session.get(ForecastModels, first)
            assert model is not None
            assert (
                model.name,
                model.nickname,
                model.org,
                model.open_source,
                model.is_enabled,
                model.security_classification_id,
            ) == ("default", "Timestral", "Mistral AI", True, True, None)
            providers = (
                await session.scalars(
                    sa.select(ModelProviders).where(
                        ModelProviders.tenant_id == admin_user.tenant_id,
                        ModelProviders.provider_type == TOOL_SERVICE,
                    )
                )
            ).all()
            assert [p.id for p in providers] == [model.provider_id]
            [provider] = providers
            # The connection stays in the deployment's settings.
            assert (provider.name, provider.credentials, provider.config) == (
                "Eneo tool service",
                {},
                {},
            )
            assert provider.is_active is True

    async def test_the_model_takes_the_name_the_runtime_reports(
        self, db_container, admin_user, monkeypatch
    ):
        status = RuntimeStatus(expected_version="2.3.0", configured=True)
        status.note_model_names({("forecast", "default"): "Timestral 28M"})
        monkeypatch.setattr(
            forecast_model_provisioning,
            "runtime_status",
            AsyncMock(return_value=status),
        )

        async with db_container() as container:
            session = container.session()
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )

            model = await session.get(ForecastModels, model_id)
            assert model is not None and model.nickname == "Timestral 28M"

    async def test_a_taken_provider_name_gets_the_built_in_suffix(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            session.add(
                ModelProviders(
                    tenant_id=admin_user.tenant_id,
                    name="Eneo tool service",
                    provider_type="openai",
                    credentials={"api_key": "sk"},
                    config={},
                )
            )
            await session.flush()

            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )

            model = await session.get(ForecastModels, model_id)
            assert model is not None
            provider = await session.get(ModelProviders, model.provider_id)
            assert provider is not None
            assert (provider.name, provider.provider_type) == (
                "Eneo tool service (built in)",
                TOOL_SERVICE,
            )

    async def test_two_first_uses_at_once_give_one_provider_and_one_model(
        self, db_container, admin_user, monkeypatch
    ):
        async def slow_status():
            # Keeps each transaction open past the other's existence checks.
            await asyncio.sleep(0.5)
            return RuntimeStatus(expected_version="test")

        monkeypatch.setattr(forecast_model_provisioning, "runtime_status", slow_status)

        async def provision():
            async with db_container() as container:
                return await ensure_default_forecast_model(
                    container.session(), admin_user.tenant_id
                )

        first, second = await asyncio.gather(provision(), provision())

        assert first == second
        async with db_container() as container:
            session = container.session()
            providers = await session.scalar(
                sa.select(sa.func.count())
                .select_from(ModelProviders)
                .where(
                    ModelProviders.tenant_id == admin_user.tenant_id,
                    ModelProviders.provider_type == TOOL_SERVICE,
                )
            )
            models = await session.scalar(
                sa.select(sa.func.count())
                .select_from(ForecastModels)
                .where(ForecastModels.tenant_id == admin_user.tenant_id)
            )
            assert (providers, models) == (1, 1)

    async def test_adding_the_bundled_forecast_binds_it_to_the_default_model(
        self, db_container, admin_user, monkeypatch
    ):
        settings = client_module.get_settings().model_copy(
            update={
                "tool_runtime_url": "http://tool-runtime:3010",
                "tool_runtime_token": "t" * 40,
            }
        )
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)

        async with db_container() as container:
            service = container.mcp_server_service()
            monkeypatch.setattr(
                service,
                "_test_connection_and_discover_tools",
                AsyncMock(return_value=([], ConnectionResult(success=True))),
            )

            result = await service.create_bundled_mcp_server("forecast")

            source = result.server
            assert source.forecast_model_id is not None
            # The new row is read back with the model it runs on.
            assert source.forecast_model is not None
            assert source.forecast_model.name == "default"
            assert source.forecast_model.provider_name == "Eneo tool service"
            assert source.image_model_id is None

    async def test_adding_it_over_http_records_the_model_in_the_audit_entry(
        self, client, headers, monkeypatch
    ):
        settings = client_module.get_settings().model_copy(
            update={
                "tool_runtime_url": "http://tool-runtime:3010",
                "tool_runtime_token": "t" * 40,
            }
        )
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)
        monkeypatch.setattr(
            MCPServerService,
            "_test_connection_and_discover_tools",
            AsyncMock(return_value=([], ConnectionResult(success=True))),
        )

        with patch(
            "eneo.audit.application.audit_service.AuditService.log_async",
            new_callable=AsyncMock,
        ) as log_async:
            response = await client.post(
                "/api/v1/mcp-servers/bundled/forecast/", headers=headers, json={}
            )

        assert response.status_code == 200, response.text
        server = response.json()["server"]
        assert server["forecast_model"]["name"] == "default"
        [created] = [
            call.kwargs
            for call in log_async.await_args_list
            if call.kwargs.get("action") == ActionType.MCP_SERVER_CREATED
        ]
        assert created["metadata"]["extra"] == {
            "bundled_tool": "forecast",
            "forecast_model_id": server["forecast_model_id"],
        }


class TestSchemaInvariants:
    async def test_the_forecast_source_must_run_on_a_forecast_model(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            with pytest.raises(IntegrityError, match="ck_mcp_servers_forecast_model"):
                async with session.begin_nested():
                    await _forecast_source(session, admin_user.tenant_id, None)

    async def test_no_other_server_may_reference_one(self, db_container, admin_user):
        async with db_container() as container:
            session = container.session()
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            with pytest.raises(IntegrityError, match="ck_mcp_servers_forecast_model"):
                async with session.begin_nested():
                    session.add(
                        MCPServers(
                            tenant_id=admin_user.tenant_id,
                            name="Compute",
                            purpose="compute",
                            http_url="http://tool-runtime:3010/mcp/compute",
                            http_auth_type="bundled",
                            forecast_model_id=model_id,
                            is_enabled=False,
                        )
                    )
                    await session.flush()

    async def test_a_provider_with_a_forecast_model_cannot_be_deleted(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            model = await session.get(ForecastModels, model_id)
            assert model is not None
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        sa.delete(ModelProviders).where(
                            ModelProviders.id == model.provider_id
                        )
                    )


class TestAskTimeProjection:
    async def test_the_source_carries_and_follows_its_model(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            classification_id = (
                await _classification(session, admin_user.tenant_id)
            ).id
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            model = await session.get(ForecastModels, model_id)
            assert model is not None
            provider_id = model.provider_id
            model.security_classification_id = classification_id
            await _forecast_source(session, admin_user.tenant_id, model_id)

        async with db_container() as container:
            [source] = await get_active_capability_servers(
                container.session(), admin_user.tenant_id, "forecast"
            )
            assert source.forecast_model_id == model_id
            assert source.forecast_model is not None
            assert source.forecast_model.name == "default"
            assert source.forecast_model.nickname == "Timestral"
            assert source.forecast_model.provider_name == "Eneo tool service"
            assert source.backing_model_blocker is None
            effective = source.effective_security_classification
            assert effective is not None and effective.id == classification_id

        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.update(ForecastModels)
                .where(ForecastModels.id == model_id)
                .values(is_enabled=False)
            )
        async with db_container() as container:
            [source] = await get_active_capability_servers(
                container.session(), admin_user.tenant_id, "forecast"
            )
            assert source.readiness_reason == "model_disabled"

        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.update(ForecastModels)
                .where(ForecastModels.id == model_id)
                .values(is_enabled=True)
            )
            await session.execute(
                sa.update(ModelProviders)
                .where(ModelProviders.id == provider_id)
                .values(is_active=False)
            )
        async with db_container() as container:
            [source] = await get_active_capability_servers(
                container.session(), admin_user.tenant_id, "forecast"
            )
            assert source.readiness_reason == "model_provider_inactive"


class TestTheSourcesOwnClassification:
    async def test_it_survives_an_unrelated_edit_and_wins_over_the_models(
        self, client, db_container, admin_user, headers
    ):
        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.update(Tenants)
                .where(Tenants.id == admin_user.tenant_id)
                .values(security_enabled=True)
            )
            models_id = (
                await _classification(session, admin_user.tenant_id, "Internal", 1)
            ).id
            own_id = (
                await _classification(session, admin_user.tenant_id, "Confidential", 2)
            ).id
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            await session.execute(
                sa.update(ForecastModels)
                .where(ForecastModels.id == model_id)
                .values(security_classification_id=models_id)
            )
            source_id = (
                await _forecast_source(
                    session,
                    admin_user.tenant_id,
                    model_id,
                    security_classification_id=own_id,
                )
            ).id

        # A fresh read shows the source's own classification, not the model's.
        shown = await client.get(f"/api/v1/mcp-servers/{source_id}/", headers=headers)
        assert shown.status_code == 200, shown.text
        assert shown.json()["security_classification"]["id"] == str(own_id)

        # An edit that does not touch it keeps it.
        async with db_container() as container:
            await container.mcp_server_service().update_mcp_server(
                source_id, name="Prognos"
            )

        async with db_container() as container:
            [source] = await get_active_capability_servers(
                container.session(), admin_user.tenant_id, "forecast"
            )
            assert source.name == "Prognos"
            assert source.security_classification is not None
            assert source.security_classification.id == own_id
            effective = source.effective_security_classification
            assert effective is not None and effective.id == own_id

    async def test_without_its_own_it_follows_the_model_after_an_edit(
        self, client, db_container, admin_user, headers
    ):
        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.update(Tenants)
                .where(Tenants.id == admin_user.tenant_id)
                .values(security_enabled=True)
            )
            internal_id = (
                await _classification(session, admin_user.tenant_id, "Internal", 1)
            ).id
            confidential_id = (
                await _classification(session, admin_user.tenant_id, "Confidential", 2)
            ).id
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            await session.execute(
                sa.update(ForecastModels)
                .where(ForecastModels.id == model_id)
                .values(security_classification_id=internal_id)
            )
            source_id = (
                await _forecast_source(session, admin_user.tenant_id, model_id)
            ).id

        # The edit forms leave the class out when the admin did not change it.
        updated = await client.post(
            f"/api/v1/mcp-servers/{source_id}/",
            json={"name": "Prognos"},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["security_classification"]["id"] == str(internal_id)

        # Classified again under Admin > Models, the model takes the source with it.
        async with db_container() as container:
            await container.session().execute(
                sa.update(ForecastModels)
                .where(ForecastModels.id == model_id)
                .values(security_classification_id=confidential_id)
            )

        async with db_container() as container:
            row = await container.session().get(MCPServers, source_id)
            assert row is not None and row.security_classification_id is None
        shown = await client.get(f"/api/v1/mcp-servers/{source_id}/", headers=headers)
        assert shown.status_code == 200, shown.text
        assert shown.json()["security_classification"]["id"] == str(confidential_id)


class TestGovernance:
    async def test_an_admin_lists_and_governs_the_model_in_one_audited_call(
        self, client, db_container, admin_user, headers
    ):
        async with db_container() as container:
            session = container.session()
            # Classifications are shown on servers only where they apply.
            await session.execute(
                sa.update(Tenants)
                .where(Tenants.id == admin_user.tenant_id)
                .values(security_enabled=True)
            )
            classification_id = (
                await _classification(session, admin_user.tenant_id)
            ).id
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            source_id = (
                await _forecast_source(session, admin_user.tenant_id, model_id)
            ).id

        listed = await client.get("/api/v1/forecast-models/", headers=headers)
        assert listed.status_code == 200, listed.text
        [item] = listed.json()["items"]
        assert item["id"] == str(model_id)
        assert (item["name"], item["nickname"], item["org"]) == (
            "default",
            "Timestral",
            "Mistral AI",
        )
        assert (item["provider_name"], item["provider_type"]) == (
            "Eneo tool service",
            TOOL_SERVICE,
        )
        assert item["is_org_enabled"] is True
        assert item["used_by_mcp_servers"] == [
            {"id": str(source_id), "name": "Forecast", "purpose": "forecast"}
        ]

        with patch(
            "eneo.audit.application.audit_service.AuditService.log_async",
            new_callable=AsyncMock,
        ) as log_async:
            updated = await client.post(
                f"/api/v1/forecast-models/{model_id}/",
                headers=headers,
                json={
                    "is_org_enabled": False,
                    "security_classification": {"id": str(classification_id)},
                    "display_name": "Timestral (CPU)",
                },
            )

        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["is_org_enabled"] is False
        assert body["nickname"] == "Timestral (CPU)"
        assert body["security_classification"]["id"] == str(classification_id)
        [audit] = [
            call.kwargs
            for call in log_async.await_args_list
            if call.kwargs.get("action") == ActionType.FORECAST_MODEL_UPDATED
        ]
        assert audit["tenant_id"] == admin_user.tenant_id
        assert audit["entity_type"] == EntityType.FORECAST_MODEL
        assert audit["entity_id"] == model_id
        assert audit["metadata"]["changes"] == {
            "is_org_enabled": {"old": True, "new": False},
            "security_classification": {"old": None, "new": "Internal"},
            "display_name": {"old": "Timestral", "new": "Timestral (CPU)"},
        }

        # The source follows its model: disabled, and classified by it.
        server = await client.get(f"/api/v1/mcp-servers/{source_id}/", headers=headers)
        assert server.status_code == 200, server.text
        server_body = server.json()
        assert server_body["forecast_model_id"] == str(model_id)
        assert server_body["forecast_model"]["nickname"] == "Timestral (CPU)"
        assert server_body["forecast_model"]["is_enabled"] is False
        assert server_body["readiness_reason"] == "model_disabled"
        assert server_body["security_classification"]["id"] == str(classification_id)

        catalog = await client.get("/api/v1/ai-models/", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert [m["id"] for m in catalog.json()["forecast_models"]] == [str(model_id)]

    async def test_an_unchanged_update_writes_no_audit_entry(
        self, client, db_container, admin_user, headers
    ):
        async with db_container() as container:
            model_id = await ensure_default_forecast_model(
                container.session(), admin_user.tenant_id
            )

        with patch(
            "eneo.audit.application.audit_service.AuditService.log_async",
            new_callable=AsyncMock,
        ) as log_async:
            response = await client.post(
                f"/api/v1/forecast-models/{model_id}/",
                headers=headers,
                json={"is_org_enabled": True, "display_name": "Timestral"},
            )

        assert response.status_code == 200, response.text
        assert not [
            call
            for call in log_async.await_args_list
            if call.kwargs.get("action") == ActionType.FORECAST_MODEL_UPDATED
        ]

    @pytest.mark.parametrize("display_name", ["", "   ", "x" * 201])
    async def test_a_blank_or_overlong_name_is_refused(
        self, client, db_container, admin_user, headers, display_name
    ):
        async with db_container() as container:
            model_id = await ensure_default_forecast_model(
                container.session(), admin_user.tenant_id
            )

        response = await client.post(
            f"/api/v1/forecast-models/{model_id}/",
            headers=headers,
            json={"display_name": display_name},
        )

        assert response.status_code == 422, response.text

    async def test_another_tenants_model_is_not_found(
        self, client, db_container, headers, tenant_factory
    ):
        async with db_container() as container:
            session = container.session()
            other = await tenant_factory(session)
            other_model_id = await ensure_default_forecast_model(session, other.id)

        for model_id in (other_model_id, uuid4()):
            response = await client.post(
                f"/api/v1/forecast-models/{model_id}/",
                headers=headers,
                json={"is_org_enabled": False},
            )
            assert response.status_code == 404, response.text

        async with db_container() as container:
            model = await container.session().get(ForecastModels, other_model_id)
            assert model is not None and model.is_enabled is True


async def _rename_while_another_update_runs(db_container, model_id, other_change):
    """Rename the model while another admin's update runs in its own session.

    The other update starts between the rename's read and its write. Unless
    the rename holds the row, it reads, writes and commits in that gap.
    """
    other: asyncio.Task[object] | None = None

    async def other_update():
        async with db_container() as container:
            await container.forecast_model_crud_service().update_forecast_model(
                model_id=model_id, **other_change
            )

    async with db_container() as container:
        service = container.forecast_model_crud_service()
        write = service.forecast_model_repo.update

        async def write_after_the_other_update_ran(*args, **kwargs):
            nonlocal other
            other = asyncio.create_task(other_update())
            await asyncio.wait({other}, timeout=1)
            return await write(*args, **kwargs)

        service.forecast_model_repo.update = write_after_the_other_update_ran
        await service.update_forecast_model(
            model_id=model_id, display_name="Timestral (CPU)"
        )

    assert other is not None
    await other
    async with db_container() as container:
        model = await container.session().get(ForecastModels, model_id)
        assert model is not None
        return model.nickname, model.is_enabled, model.security_classification_id


class TestConcurrentUpdates:
    """Two admins changing the model at once: neither undoes the other."""

    async def test_a_rename_keeps_a_concurrent_disable(self, db_container, admin_user):
        async with db_container() as container:
            model_id = await ensure_default_forecast_model(
                container.session(), admin_user.tenant_id
            )

        with patch(
            "eneo.audit.application.audit_service.AuditService.log_async",
            new_callable=AsyncMock,
        ):
            nickname, is_enabled, _ = await _rename_while_another_update_runs(
                db_container, model_id, {"is_org_enabled": False}
            )

        assert (nickname, is_enabled) == ("Timestral (CPU)", False)

    async def test_a_rename_keeps_a_concurrent_classification(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            classification_id = (
                await _classification(session, admin_user.tenant_id)
            ).id
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )

        with patch(
            "eneo.audit.application.audit_service.AuditService.log_async",
            new_callable=AsyncMock,
        ):
            (
                nickname,
                _,
                kept_classification_id,
            ) = await _rename_while_another_update_runs(
                db_container,
                model_id,
                {"security_classification": ModelId(id=classification_id)},
            )

        assert (nickname, kept_classification_id) == (
            "Timestral (CPU)",
            classification_id,
        )


class TestTheToolServiceProvider:
    async def test_it_comes_with_the_deployment(
        self, client, db_container, admin_user, headers
    ):
        async with db_container() as container:
            session = container.session()
            model_id = await ensure_default_forecast_model(
                session, admin_user.tenant_id
            )
            model = await session.get(ForecastModels, model_id)
            assert model is not None
            provider_id = model.provider_id
            classification_id = (
                await _classification(session, admin_user.tenant_id)
            ).id
            model.security_classification_id = classification_id

        providers = await client.get("/api/v1/admin/model-providers/", headers=headers)
        assert providers.status_code == 200, providers.text
        [managed] = [p for p in providers.json() if p["id"] == str(provider_id)]
        assert managed["is_managed"] is True
        assert managed["provider_type"] == TOOL_SERVICE

        for response in (
            await client.put(
                f"/api/v1/admin/model-providers/{provider_id}/",
                headers=headers,
                json={"name": "Renamed"},
            ),
            await client.delete(
                f"/api/v1/admin/model-providers/{provider_id}/", headers=headers
            ),
            await client.post(
                "/api/v1/admin/tenant-models/completion/",
                headers=headers,
                json={
                    "provider_id": str(provider_id),
                    "name": "gpt-4o",
                    "display_name": "GPT-4o",
                    "max_input_tokens": 1000,
                    "max_output_tokens": 1000,
                },
            ),
        ):
            assert response.status_code == 400, response.text
            assert "comes with the deployment" in response.text

        # The classification the forecast model has is in use.
        deleted = await client.delete(
            f"/api/v1/security-classifications/{classification_id}/", headers=headers
        )
        assert deleted.status_code == 400, deleted.text
        assert "forecast_models" in deleted.text
