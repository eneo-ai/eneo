"""A model whose classification drops below its space's stays linked to it.

Lowering a model's security classification used to make the space stop
listing it, and the next save of anything in that space rewrote the space's
model links from that shortened list, so the link was gone for good. The link
now survives every unrelated save; the model is not usable in the space and is
reported as below the space's classification, so an admin decides whether to
raise the model's classification, change the space's, or remove it."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.spaces_table import Spaces, SpacesCompletionModels
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True)
class Setup:
    headers: dict[str, str]
    tenant_id: UUID
    space_id: UUID
    lowered_model_id: UUID
    kept_model_id: UUID
    assistant_id: UUID


async def _token(db_container, admin_user) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"below-classification-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.APPS,
                    Permission.GROUP_CHATS,
                    Permission.SHARED_SPACES,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        return container.auth_service().create_access_token_for_user(admin)


async def _links(db_container, space_id: UUID) -> set[UUID]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(SpacesCompletionModels.completion_model_id).where(
                SpacesCompletionModels.space_id == space_id
            )
        )
        return set(rows.all())


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, UUID]]:
    audited: list[tuple[str, UUID]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        audited.append((str(kwargs["action"].value), kwargs["entity_id"]))
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return audited


@pytest.fixture
async def setup(
    client,
    db_container,
    admin_user,
    completion_model_factory,
    transcription_model_factory,
    patch_auth_service_jwt,
) -> Setup:
    token = await _token(db_container, admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    tenant_id = admin_user.tenant_id

    async with db_container() as container:
        session = container.session()
        high = SecurityClassifications(
            tenant_id=tenant_id, name=f"high-{uuid4().hex[:6]}", security_level=20
        )
        session.add(high)
        await session.flush()
        lowered = await completion_model_factory(
            session, f"lowered-{uuid4().hex[:6]}", is_default=True
        )
        kept = await completion_model_factory(session, f"kept-{uuid4().hex[:6]}")
        transcription = await transcription_model_factory(
            session, f"whisper-{uuid4().hex[:6]}", security_classification_id=high.id
        )
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id.in_([lowered.id, kept.id]))
            .values(security_classification_id=high.id)
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(security_enabled=True)
        )
        high_id, lowered_id, kept_id = high.id, lowered.id, kept.id
        transcription_id = transcription.id

    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"below-classification-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    space_id = UUID(response.json()["id"])
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={
            "completion_models": [{"id": str(lowered_id)}, {"id": str(kept_id)}],
            "transcription_models": [{"id": str(transcription_id)}],
            "security_classification": {"id": str(high_id)},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "uses the lowered model"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assistant_id = UUID(response.json()["id"])
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"completion_model": {"id": str(lowered_id)}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, space_id) >= {lowered_id, kept_id}

    # An admin lowers the model's classification below the space's.
    async with db_container() as container:
        session = container.session()
        low = SecurityClassifications(
            tenant_id=tenant_id, name=f"low-{uuid4().hex[:6]}", security_level=1
        )
        session.add(low)
        await session.flush()
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == lowered_id)
            .values(security_classification_id=low.id)
        )

    return Setup(
        headers=headers,
        tenant_id=tenant_id,
        space_id=space_id,
        lowered_model_id=lowered_id,
        kept_model_id=kept_id,
        assistant_id=assistant_id,
    )


async def test_unrelated_saves_keep_the_space_model_link(
    client, db_container, setup: Setup, monkeypatch: pytest.MonkeyPatch
):
    audited = _record_audit(monkeypatch)
    saves = [
        (
            "update an assistant",
            client.post(
                f"/api/v1/assistants/{setup.assistant_id}/",
                json={"name": "renamed"},
                headers=setup.headers,
            ),
            200,
        ),
        (
            "create an assistant",
            client.post(
                f"/api/v1/spaces/{setup.space_id}/applications/assistants/",
                json={"name": "another assistant"},
                headers=setup.headers,
            ),
            201,
        ),
        (
            "create an app",
            client.post(
                f"/api/v1/spaces/{setup.space_id}/applications/apps/",
                json={"name": "an app"},
                headers=setup.headers,
            ),
            201,
        ),
        (
            "create a group chat",
            client.post(
                f"/api/v1/spaces/{setup.space_id}/applications/group-chats/",
                json={"name": "a group chat"},
                headers=setup.headers,
            ),
            201,
        ),
        (
            "rename the space",
            client.patch(
                f"/api/v1/spaces/{setup.space_id}/",
                json={"name": "renamed space"},
                headers=setup.headers,
            ),
            200,
        ),
    ]
    for label, request, status in saves:
        response = await request
        assert response.status_code == status, (label, response.text)
        assert setup.lowered_model_id in await _links(db_container, setup.space_id), (
            label
        )

    # The saves audit what they did and nothing about the model or its link.
    assert all(entity_id != setup.lowered_model_id for _, entity_id in audited)
    assert [action for action, _ in audited] == [
        "assistant_updated",
        "assistant_created",
        "app_created",
        "group_chat_created",
        "space_updated",
    ]

    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == setup.space_id
            )
        )
        model_classification = await container.session().scalar(
            sa.select(CompletionModels.security_classification_id).where(
                CompletionModels.id == setup.lowered_model_id
            )
        )
    # Nothing reclassified anything.
    assert stored is not None and model_classification is not None
    assert stored != model_classification


async def test_the_space_reports_the_model_as_below_its_classification(
    client, setup: Setup
):
    response = await client.get(
        f"/api/v1/spaces/{setup.space_id}/", headers=setup.headers
    )
    assert response.status_code == 200, response.text
    space = response.json()

    usable = {model["id"] for model in space["completion_models"]}
    assert str(setup.lowered_model_id) not in usable
    assert str(setup.kept_model_id) in usable
    # Every link, marked with its state; only the kept model is usable.
    links = {link["id"]: link for link in space["linked_models"]["completion_models"]}
    assert set(links) == {str(setup.lowered_model_id), str(setup.kept_model_id)}
    lowered = links[str(setup.lowered_model_id)]
    assert lowered["meets_security_classification"] is False
    assert lowered["available"] is True
    kept = links[str(setup.kept_model_id)]
    assert kept["meets_security_classification"] is True
    assert kept["available"] is True
    assert [
        link["meets_security_classification"]
        for link in (space["linked_models"]["transcription_models"])
    ] == [True]
    assert "models_below_security_classification" not in space


async def test_the_model_cannot_be_selected_at_the_spaces_level(
    client, db_container, setup: Setup
):
    response = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/",
        json={"completion_model": {"id": str(setup.kept_model_id)}},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text

    # Selecting it again fails closed; nothing substitutes another model.
    response = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/",
        json={"completion_model": {"id": str(setup.lowered_model_id)}},
        headers=setup.headers,
    )
    assert response.status_code in (400, 403), response.text
    response = await client.get(
        f"/api/v1/assistants/{setup.assistant_id}/", headers=setup.headers
    )
    assert response.json()["completion_model"]["id"] == str(setup.kept_model_id)
    assert setup.lowered_model_id in await _links(db_container, setup.space_id)


async def test_an_assistant_on_the_model_cannot_be_asked(client, setup: Setup):
    response = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/sessions/",
        json={"question": "Hej", "stream": False},
        headers=setup.headers,
    )
    assert response.status_code in (400, 403), response.text


async def test_explicit_removal_unlinks_the_model(client, db_container, setup: Setup):
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"completion_models": [{"id": str(setup.kept_model_id)}]},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, setup.space_id) == {setup.kept_model_id}
    assert [
        link["id"] for link in response.json()["linked_models"]["completion_models"]
    ] == [str(setup.kept_model_id)]


async def test_resubmitting_the_linked_models_keeps_the_link(
    client, db_container, setup: Setup
):
    # What the settings page sends when an admin toggles another model while
    # this one is marked: the full linked list.
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={
            "completion_models": [
                {"id": str(setup.kept_model_id)},
                {"id": str(setup.lowered_model_id)},
            ]
        },
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, setup.space_id) == {
        setup.kept_model_id,
        setup.lowered_model_id,
    }


async def _linked_ids_from_the_space(client, setup: Setup) -> list[str]:
    # What the settings page resubmits: every link the space reports.
    response = await client.get(
        f"/api/v1/spaces/{setup.space_id}/", headers=setup.headers
    )
    assert response.status_code == 200, response.text
    return [
        link["id"] for link in response.json()["linked_models"]["completion_models"]
    ]


async def test_restating_the_spaces_classification_keeps_the_link(
    client, db_container, setup: Setup
):
    async with db_container() as container:
        classification_id = await container.session().scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == setup.space_id
            )
        )
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"security_classification": {"id": str(classification_id)}},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert setup.lowered_model_id in await _links(db_container, setup.space_id)


async def test_toggling_another_model_keeps_a_disabled_model_below_the_level(
    client, db_container, setup: Setup, completion_model_factory
):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == setup.lowered_model_id)
            .values(is_enabled=False)
        )
        high_id = await session.scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == setup.space_id
            )
        )
        another = await completion_model_factory(
            session, f"another-{uuid4().hex[:6]}", security_classification_id=high_id
        )
        another_id = another.id
    ids = await _linked_ids_from_the_space(client, setup)
    assert str(setup.lowered_model_id) in ids

    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"completion_models": [{"id": i} for i in [*ids, str(another_id)]]},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, setup.space_id) == {
        setup.lowered_model_id,
        setup.kept_model_id,
        another_id,
    }


async def test_explicit_removal_is_in_the_audit_diff(
    client, setup: Setup, monkeypatch: pytest.MonkeyPatch
):
    recorded: list[dict[str, object]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        recorded.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"completion_models": [{"id": str(setup.kept_model_id)}]},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text

    (space_update,) = [r for r in recorded if r["action"].value == "space_updated"]
    change = space_update["metadata"]["changes"]["completion_models"]
    assert str(setup.lowered_model_id) in {m["id"] for m in change["old"]}
    assert str(setup.lowered_model_id) not in {m["id"] for m in change["new"]}


async def test_toggling_another_model_keeps_a_disabled_compatible_model(
    client, db_container, setup: Setup, completion_model_factory
):
    # The counterpart: a model that meets the classification but that the
    # tenant disabled is hidden from the usable lists, yet stays linked.
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == setup.kept_model_id)
            .values(is_enabled=False)
        )
        high_id = await session.scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == setup.space_id
            )
        )
        another = await completion_model_factory(
            session, f"another-{uuid4().hex[:6]}", security_classification_id=high_id
        )
        another_id = another.id
    response = await client.get(
        f"/api/v1/spaces/{setup.space_id}/", headers=setup.headers
    )
    space = response.json()
    assert str(setup.kept_model_id) not in {m["id"] for m in space["completion_models"]}
    links = {link["id"]: link for link in space["linked_models"]["completion_models"]}
    assert links[str(setup.kept_model_id)]["available"] is False
    assert links[str(setup.kept_model_id)]["meets_security_classification"] is True

    ids = await _linked_ids_from_the_space(client, setup)
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"completion_models": [{"id": i} for i in [*ids, str(another_id)]]},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, setup.space_id) == {
        setup.lowered_model_id,
        setup.kept_model_id,
        another_id,
    }


async def test_a_classification_change_that_removes_links_is_in_the_audit_diff(
    client, db_container, setup: Setup, monkeypatch: pytest.MonkeyPatch
):
    recorded: list[dict[str, object]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        recorded.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    async with db_container() as container:
        session = container.session()
        higher = SecurityClassifications(
            tenant_id=setup.tenant_id,
            name=f"higher-{uuid4().hex[:6]}",
            security_level=30,
        )
        session.add(higher)
        await session.flush()
        higher_id = higher.id

    # The admin raises the space's level: every model below it is removed.
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"security_classification": {"id": str(higher_id)}},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert setup.lowered_model_id not in await _links(db_container, setup.space_id)

    (space_update,) = [r for r in recorded if r["action"].value == "space_updated"]
    change = space_update["metadata"]["changes"]["completion_models"]
    assert str(setup.lowered_model_id) in {m["id"] for m in change["old"]}
    assert str(setup.lowered_model_id) not in {m["id"] for m in change["new"]}


async def test_a_retired_link_survives_an_unrelated_save(
    client, db_container, setup: Setup
):
    # A deprecated model is not loaded into the space, so no edit can see it;
    # an unrelated save must leave its stored link alone.
    async with db_container() as container:
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == setup.kept_model_id)
            .values(is_deprecated=True)
        )

    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"name": "renamed space"},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert setup.kept_model_id in await _links(db_container, setup.space_id)

    # A model-list edit built from the links the space reports keeps it too.
    ids = await _linked_ids_from_the_space(client, setup)
    assert str(setup.kept_model_id) not in ids
    response = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        json={"completion_models": [{"id": i} for i in ids]},
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    assert await _links(db_container, setup.space_id) == {
        setup.kept_model_id,
        setup.lowered_model_id,
    }


async def test_the_space_api_requires_the_link_lists(client, setup: Setup):
    from eneo.server.main import get_application

    schemas = get_application().openapi()["components"]["schemas"]
    assert "linked_models" in schemas["SpacePublic"]["required"]
    assert set(schemas["SpaceLinkedModels"]["required"]) == {
        "completion_models",
        "embedding_models",
        "transcription_models",
    }
