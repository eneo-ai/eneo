"""Each blocked Skill lifecycle action must name itself over HTTP.

Every conflict below used to arrive as one of two shared reason codes, so a
client could not tell "slug taken" from "still attached" from "published", and
the localized recovery instruction it showed was whichever one the shared code
happened to own. These tests pin the status and the reason code a client reads
to choose that instruction.
"""

from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.skill_table import Skills
from eneo.main.exceptions import ErrorCodes
from eneo.server.exception_handlers import add_exception_handlers
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
    SkillExecutionBlockConflictError,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillRemovalBusyError,
    SkillSlugConflictError,
)

SKILL_CONFLICT_WIRE_CONTRACT = [
    (SkillSlugConflictError, ErrorCodes.SKILL_SLUG_TAKEN),
    (SkillRemovalBusyError, ErrorCodes.SKILL_REMOVAL_BUSY),
    # Hard-delete invariant for direct repository callers, not organisation removal.
    (PublishedSkillDeletionError, ErrorCodes.SKILL_PUBLISHED_NOT_DELETABLE),
    (SkillHasActiveAppRunsError, ErrorCodes.SKILL_IN_USE_BY_APP_RUN),
    (SkillHasBindingsError, ErrorCodes.SKILL_STILL_ATTACHED),
    (SkillExecutionBlockConflictError, ErrorCodes.SKILL_EXECUTION_BLOCK_CONFLICT),
]


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _conflict(response) -> tuple[int, int]:
    return response.status_code, response.json()["eneo_error_code"]


async def _create_space(client, *, token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"skill-conflicts-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_space_skill(client, *, token: str, space_id: str, slug: str) -> dict:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={
            "slug": slug,
            "display_name": "Payroll",
            "description": "Answers approved payroll questions.",
            "instructions": "Use approved payroll sources.",
        },
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_assistant(client, *, token: str, space_id: str) -> str:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Payroll assistant"},
        headers=_auth(token),
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _create_organization_skill(client, *, token: str, slug: str) -> dict:
    response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": slug,
            "display_name": "Payroll",
            "description": "Answers approved payroll questions.",
            "instructions": "Use approved payroll sources.",
        },
        headers=_auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_taken_slug_is_reported_as_a_slug_conflict_in_both_scopes(
    client, admin_token
):
    slug = f"payroll-{uuid4().hex[:8]}"
    space_id = await _create_space(client, token=admin_token)
    await _create_space_skill(client, token=admin_token, space_id=space_id, slug=slug)

    space_retry = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={
            "slug": slug,
            "display_name": "Payroll again",
            "description": "Answers approved payroll questions.",
            "instructions": "Use approved payroll sources.",
        },
        headers=_auth(admin_token),
    )
    assert _conflict(space_retry) == (409, ErrorCodes.SKILL_SLUG_TAKEN)

    organization_slug = f"payroll-org-{uuid4().hex[:8]}"
    await _create_organization_skill(client, token=admin_token, slug=organization_slug)
    organization_retry = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": organization_slug,
            "display_name": "Payroll again",
            "description": "Answers approved payroll questions.",
            "instructions": "Use approved payroll sources.",
        },
        headers=_auth(admin_token),
    )
    assert _conflict(organization_retry) == (409, ErrorCodes.SKILL_SLUG_TAKEN)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_publish_and_stale_restore_report_a_revision_conflict(
    client, admin_token
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug=f"budget-{uuid4().hex[:8]}"
    )
    reviewed_revision_id = skill["current_revision"]["id"]

    revise = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/revisions/",
        json={
            "display_name": "Budget support",
            "description": "Answers approved budget questions.",
            "instructions": "Use the newest approved budget sources.",
        },
        headers=_auth(admin_token),
    )
    assert revise.status_code in (200, 201), revise.text

    stale_publish = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": reviewed_revision_id},
        headers=_auth(admin_token),
    )
    assert _conflict(stale_publish) == (409, ErrorCodes.SKILL_REVISION_CONFLICT)

    stale_restore = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/revisions/"
        f"{reviewed_revision_id}/restore/",
        json={"reviewed_current_revision_id": reviewed_revision_id},
        headers=_auth(admin_token),
    )
    assert _conflict(stale_restore) == (409, ErrorCodes.SKILL_REVISION_CONFLICT)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removed_organisation_skill_retains_readable_history_and_releases_slug(
    client, admin_token, db_container
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug=f"retained-{uuid4().hex[:8]}"
    )
    publish = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert publish.status_code == 200, publish.text

    unpublish = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/unpublish/",
        headers=_auth(admin_token),
    )
    assert unpublish.status_code == 200, unpublish.text

    delete = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/",
        headers=_auth(admin_token),
    )
    assert delete.status_code == 204, delete.text
    retained = await client.get(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert retained.status_code == 200, retained.text
    assert retained.json()["removed_at"] is not None
    assert retained.json()["current_revision"] == skill["current_revision"]
    assert retained.json()["usage"] == {
        "assistant_count": 0,
        "app_count": 0,
        "distinct_space_count": 0,
        "personal_chat_pinned": False,
    }
    current = await client.get(
        "/api/v1/skills/organization/", headers=_auth(admin_token)
    )
    assert skill["id"] not in [item["id"] for item in current.json()["items"]]
    removed = await client.get(
        "/api/v1/skills/organization/?removed=true", headers=_auth(admin_token)
    )
    assert skill["id"] in [item["id"] for item in removed.json()["items"]]
    repeated = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert repeated.status_code == 204, repeated.text

    async with db_container() as container:
        logs = list(
            await container.session().scalars(
                sa.select(AuditLog.log_metadata).where(
                    AuditLog.entity_id == skill["id"],
                    AuditLog.action == ActionType.SKILL_DELETED.value,
                )
            )
        )
    assert len(logs) == 1
    assert logs[0]["extra"]["history_retained"] is True
    assert "instructions" not in str(logs[0])

    revision_id = skill["current_revision"]["id"]
    for path, body in [
        ("unpublish/", {}),
        ("publish/", {"expected_revision_id": revision_id}),
        (
            "revisions/",
            {
                "display_name": "Changed",
                "description": "Changed",
                "instructions": "Changed",
            },
        ),
        (
            f"revisions/{revision_id}/restore/",
            {"reviewed_current_revision_id": revision_id},
        ),
    ]:
        response = await client.post(
            f"/api/v1/skills/organization/{skill['id']}/{path}",
            json=body,
            headers=_auth(admin_token),
        )
        assert response.status_code == 404, response.text

    replacement = await _create_organization_skill(
        client, token=admin_token, slug=skill["slug"]
    )
    assert replacement["id"] != skill["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_removal_is_atomic_and_identifies_bound_skills(
    client, admin_token, db_container
):
    free = await _create_organization_skill(client, token=admin_token, slug="unused")
    bound = await _create_organization_skill(client, token=admin_token, slug="used")
    published = await client.post(
        f"/api/v1/skills/organization/{bound['id']}/publish/",
        json={"expected_revision_id": bound["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert published.status_code == 200, published.text
    space_id = await _create_space(client, token=admin_token)
    assistant_id = await _create_assistant(client, token=admin_token, space_id=space_id)
    attach = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": bound["id"],
                    "skill_revision_id": bound["current_revision"]["id"],
                }
            ]
        },
        headers=_auth(admin_token),
    )
    assert attach.status_code == 200, attach.text
    ids = [free["id"], bound["id"]]
    refused = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": ids},
        headers=_auth(admin_token),
    )
    assert _conflict(refused) == (409, ErrorCodes.SKILL_STILL_ATTACHED)
    async with db_container() as container:
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.entity_id.in_(ids),
                    AuditLog.action == ActionType.SKILL_DELETED.value,
                )
            )
            == 0
        )
    assert refused.json()["details"]["skill_ids"] == [bound["id"]]
    listing = await client.get(
        "/api/v1/skills/organization/", headers=_auth(admin_token)
    )
    items = {item["id"]: item for item in listing.json()["items"]}
    assert items[free["id"]]["removed_at"] is None
    assert items[bound["id"]]["usage"]["assistant_count"] == 1
    assert items[bound["id"]]["usage"]["distinct_space_count"] == 1

    invalid = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": [free["id"], str(uuid4())]},
        headers=_auth(admin_token),
    )
    assert invalid.status_code == 404
    detach = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"skill_bindings": []},
        headers=_auth(admin_token),
    )
    assert detach.status_code == 200, detach.text
    removed = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": ids},
        headers=_auth(admin_token),
    )
    assert removed.status_code == 200, removed.text
    assert set(removed.json()["removed_ids"]) == set(ids)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ids", [[], [str(uuid4())] * 2, [str(uuid4()) for _ in range(101)]]
)
async def test_bulk_removal_requires_a_bounded_distinct_selection(
    client, admin_token, ids
):
    response = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": ids},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_attached_skill_reports_a_distinct_delete_conflict(client, admin_token):
    space_id = await _create_space(client, token=admin_token)
    skill = await _create_space_skill(
        client,
        token=admin_token,
        space_id=space_id,
        slug=f"attached-{uuid4().hex[:8]}",
    )

    assistant_id = await _create_assistant(client, token=admin_token, space_id=space_id)
    attach = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": skill["id"],
                    "skill_revision_id": skill["current_revision"]["id"],
                }
            ]
        },
        headers=_auth(admin_token),
    )
    assert attach.status_code == 200, attach.text

    delete = await client.delete(
        f"/api/v1/spaces/{space_id}/skills/{skill['id']}/",
        headers=_auth(admin_token),
    )
    assert _conflict(delete) == (409, ErrorCodes.SKILL_STILL_ATTACHED)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_execution_block_no_longer_borrows_the_revision_conflict(
    client, admin_token
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug=f"incident-{uuid4().hex[:8]}"
    )
    publish = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert publish.status_code == 200, publish.text

    block = await client.post(
        f"/api/v1/settings/skills/{skill['id']}/execution-block",
        json={"reason": "Confirmed unsafe instructions"},
        headers=_auth(admin_token),
    )
    assert block.status_code == 200, block.text
    reviewed_block_id = block.json()["block"]["id"]

    released = await client.post(
        f"/api/v1/settings/skills/{skill['id']}/execution-block/unblock",
        json={
            "expected_block_id": reviewed_block_id,
            "reason": "Revision removed from affected resources",
        },
        headers=_auth(admin_token),
    )
    assert released.status_code == 200, released.text

    # A second administrator still holding the released block loses the race.
    stale = await client.post(
        f"/api/v1/settings/skills/{skill['id']}/execution-block/unblock",
        json={
            "expected_block_id": reviewed_block_id,
            "reason": "Revision removed from affected resources",
        },
        headers=_auth(admin_token),
    )
    assert _conflict(stale) == (409, ErrorCodes.SKILL_EXECUTION_BLOCK_CONFLICT)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unsupported_activation_mode_stays_a_bad_request(client, admin_token):
    space_id = await _create_space(client, token=admin_token)
    skill = await _create_space_skill(
        client,
        token=admin_token,
        space_id=space_id,
        slug=f"binding-mode-{uuid4().hex[:8]}",
    )
    assistant_id = await _create_assistant(client, token=admin_token, space_id=space_id)

    # On demand without an explicit tool-capable model is a configuration
    # limit, not a conflict; it keeps its 400 rather than joining the 409 set.
    rejected = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": skill["id"],
                    "skill_revision_id": skill["current_revision"]["id"],
                    "activation_mode": "on_demand",
                }
            ]
        },
        headers=_auth(admin_token),
    )
    assert rejected.status_code == 400, rejected.text
    body = rejected.json()
    assert body["eneo_error_code"] == ErrorCodes.BAD_REQUEST
    assert "on-demand" in body["message"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain_error", "expected_code"),
    SKILL_CONFLICT_WIRE_CONTRACT,
    ids=[error.__name__ for error, _ in SKILL_CONFLICT_WIRE_CONTRACT],
)
async def test_every_registered_skill_conflict_reaches_the_client_named(
    domain_error: type[Exception],
    expected_code: ErrorCodes,
):
    """Cover the registration itself, including conflicts whose real trigger
    needs a concurrent writer that an HTTP scenario cannot hold open."""
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/raise/")
    async def raise_conflict():  # pragma: no cover - body is the raise
        raise domain_error()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise/")

    assert _conflict(response) == (409, expected_code)
    # An unregistered conflict would fall through to a 500 with no instruction,
    # so the body must carry the English fallback the handler owns.
    assert response.json()["message"].strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removed_catalogue_paginates_reused_slugs_without_skips(
    client, admin_token
):
    removed_ids = set()
    for _ in range(3):
        skill = await _create_organization_skill(
            client, token=admin_token, slug="reused-slug"
        )
        response = await client.delete(
            f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
        )
        assert response.status_code == 204, response.text
        removed_ids.add(skill["id"])
    seen = []
    cursor = None
    for _ in range(3):
        response = await client.get(
            "/api/v1/skills/organization/",
            params={
                "removed": "true",
                "limit": 1,
                **({"cursor": cursor} if cursor else {}),
            },
            headers=_auth(admin_token),
        )
        assert response.status_code == 200, response.text
        seen.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["next_cursor"]
    assert cursor is None
    assert len(seen) == 3
    assert set(seen) == removed_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removal_requires_session_auth(client, admin_token, admin_user_api_key):
    skill = await _create_organization_skill(
        client, token=admin_token, slug="session-only"
    )
    headers = {"X-API-Key": admin_user_api_key.key}
    for response in [
        await client.delete(
            f"/api/v1/skills/organization/{skill['id']}/", headers=headers
        ),
        await client.post(
            "/api/v1/skills/organization/remove/",
            json={"skill_ids": [skill["id"]]},
            headers=headers,
        ),
    ]:
        assert response.status_code == 403, response.text
    current = await client.get(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert current.json()["removed_at"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_removal_retains_an_existing_execution_block_until_explicitly_closed(
    client, admin_token
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug="removed-incident"
    )
    published = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert published.status_code == 200, published.text
    path = f"/api/v1/settings/skills/{skill['id']}/execution-block"
    blocked = await client.post(
        path, json={"reason": "Incident investigation"}, headers=_auth(admin_token)
    )
    assert blocked.status_code == 200, blocked.text
    block_id = blocked.json()["block"]["id"]
    removed = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert removed.status_code == 204, removed.text
    retained = await client.get(path, headers=_auth(admin_token))
    assert retained.json()["block"]["id"] == block_id
    closed = await client.post(
        f"{path}/unblock",
        json={"expected_block_id": block_id, "reason": "Retired after investigation"},
        headers=_auth(admin_token),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["block"] is None
    new_block = await client.post(
        path,
        json={"reason": "Cannot change a removed Skill"},
        headers=_auth(admin_token),
    )
    assert new_block.status_code == 404, new_block.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_removal_reports_a_live_database_lock_as_retryable_conflict(
    client,
    admin_token,
    db_container,
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug="locked-removal"
    )
    async with db_container() as writer:
        await writer.session().execute(
            sa.select(Skills.id)
            .where(Skills.id == skill["id"])
            .with_for_update(read=True)
        )
        refused = await client.post(
            "/api/v1/skills/organization/remove/",
            json={"skill_ids": [skill["id"]]},
            headers=_auth(admin_token),
        )
        assert _conflict(refused) == (409, ErrorCodes.SKILL_REMOVAL_BUSY)
    current = await client.get(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert current.json()["removed_at"] is None
    retry = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": [skill["id"]]},
        headers=_auth(admin_token),
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["removed_ids"] == [skill["id"]]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_detaching_removal_removes_bound_skill_and_reports_totals(
    client, admin_token, db_container
):
    bound = await _create_organization_skill(
        client, token=admin_token, slug="detach-me"
    )
    published = await client.post(
        f"/api/v1/skills/organization/{bound['id']}/publish/",
        json={"expected_revision_id": bound["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert published.status_code == 200, published.text
    space_id = await _create_space(client, token=admin_token)
    assistant_id = await _create_assistant(client, token=admin_token, space_id=space_id)
    attach = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": bound["id"],
                    "skill_revision_id": bound["current_revision"]["id"],
                }
            ]
        },
        headers=_auth(admin_token),
    )
    assert attach.status_code == 200, attach.text

    removed = await client.post(
        "/api/v1/skills/organization/remove/",
        json={"skill_ids": [bound["id"]], "detach_bindings": True},
        headers=_auth(admin_token),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {
        "removed_ids": [bound["id"]],
        "detached": {"assistant_count": 1, "app_count": 0, "personal_chat_count": 0},
    }
    async with db_container() as container:
        assert (
            await container.skill_repo().list_assistant_bindings(
                assistant_id=assistant_id
            )
            == []
        )
        audit = await container.session().scalar(
            sa.select(AuditLog).where(
                AuditLog.entity_id == bound["id"],
                AuditLog.action == ActionType.SKILL_DELETED.value,
            )
        )
        assert audit is not None
        assert audit.log_metadata["extra"]["detached"]["assistant_ids"] == [
            assistant_id
        ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_removal_accepts_the_detach_query_parameter(
    client, admin_token, db_container
):
    skill = await _create_organization_skill(
        client, token=admin_token, slug="detach-one"
    )
    published = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=_auth(admin_token),
    )
    assert published.status_code == 200, published.text
    space_id = await _create_space(client, token=admin_token)
    assistant_id = await _create_assistant(client, token=admin_token, space_id=space_id)
    attach = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": skill["id"],
                    "skill_revision_id": skill["current_revision"]["id"],
                }
            ]
        },
        headers=_auth(admin_token),
    )
    assert attach.status_code == 200, attach.text

    strict = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/", headers=_auth(admin_token)
    )
    assert strict.status_code == 409, strict.text
    assert strict.json()["eneo_error_code"] == 9051

    response = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/?detach_bindings=true",
        headers=_auth(admin_token),
    )
    assert response.status_code == 204, response.text
    async with db_container() as container:
        repo = container.skill_repo()
        assert await repo.list_assistant_bindings(assistant_id=assistant_id) == []
        removed_at = await container.session().scalar(
            sa.select(Skills.removed_at).where(Skills.id == UUID(skill["id"]))
        )
        assert removed_at is not None
