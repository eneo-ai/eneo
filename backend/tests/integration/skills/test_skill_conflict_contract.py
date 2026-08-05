"""Each blocked Skill lifecycle action must name itself over HTTP.

Every conflict below used to arrive as one of two shared reason codes, so a
client could not tell "slug taken" from "still attached" from "published", and
the localized recovery instruction it showed was whichever one the shared code
happened to own. These tests pin the status and the reason code a client reads
to choose that instruction.
"""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from eneo.main.exceptions import ErrorCodes
from eneo.server.exception_handlers import add_exception_handlers
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
    SkillExecutionBlockConflictError,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillSlugConflictError,
)

SKILL_CONFLICT_WIRE_CONTRACT = [
    (SkillSlugConflictError, ErrorCodes.SKILL_SLUG_TAKEN),
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
async def test_published_organisation_skill_reports_its_own_delete_conflict(
    client, admin_token
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

    # Unpublishing stops new attachments, but a Skill that has ever been
    # published is retained for audit history and can never be deleted. The
    # refusal must say which of the two blockers applies.
    delete = await client.delete(
        f"/api/v1/skills/organization/{skill['id']}/",
        headers=_auth(admin_token),
    )
    assert _conflict(delete) == (409, ErrorCodes.SKILL_PUBLISHED_NOT_DELETABLE)


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
