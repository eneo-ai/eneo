"""HTTP contract for advancing the Personal Chat pin of an organisation Skill.

``POST /skills/organization/{skill_id}/personal-chat/advance/`` moves the
Personal Chat binding to the published revision the administrator reviewed.
The wire contract under test: a real advance returns the revision movement and
writes exactly one audit event; a repeat is a clean no-op without a second
audit row; a stale reviewed revision is a 409 without any write.

Seeds run through the same public APIs an administrator uses.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_advance_moves_the_pin_audits_once_and_repeats_cleanly(
    client, admin_token, db_container
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with db_container() as container:
        # The fit validation that guards the advance needs the personal
        # default assistant to exist, exactly as in production tenants.
        await container.space_init_service().get_personal_space()

    create_response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"pin-advance-{uuid4().hex[:8]}",
            "display_name": "Pin advance",
            "description": "Approved guidance.",
            "instructions": "Follow the approved instructions.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill_id = create_response.json()["id"]
    first_revision_id = create_response.json()["current_revision"]["id"]

    publish_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": first_revision_id},
        headers=headers,
    )
    assert publish_response.status_code == 200, publish_response.text

    bind_response = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "skills": {
                "bindings": [
                    {
                        "skill_id": skill_id,
                        "skill_revision_id": first_revision_id,
                    }
                ]
            }
        },
        headers=headers,
    )
    assert bind_response.status_code == 200, bind_response.text

    revision_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/revisions/",
        json={
            "display_name": "Pin advance",
            "description": "Approved guidance, revised.",
            "instructions": "Follow the second approved revision.",
        },
        headers=headers,
    )
    assert revision_response.status_code == 201, revision_response.text
    second_revision_id = revision_response.json()["id"]
    republish_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": second_revision_id},
        headers=headers,
    )
    assert republish_response.status_code == 200, republish_response.text

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        # While a write is still at stake, a reviewed revision that does not
        # match the pin is a conflict, and nothing may change or be audited.
        stale = await client.post(
            f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
            json={
                "expected_pinned_revision_id": str(uuid4()),
                "expected_published_revision_id": second_revision_id,
            },
            headers=headers,
        )
        assert stale.status_code == 409, stale.text
        assert enqueue_audit.await_count == 0

        advanced = await client.post(
            f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
            json={
                "expected_pinned_revision_id": first_revision_id,
                "expected_published_revision_id": second_revision_id,
            },
            headers=headers,
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json() == {
            "outcome": "advanced",
            "from_revision_number": 1,
            "to_revision_number": 2,
        }
        assert enqueue_audit.await_count == 1
        assert enqueue_audit.await_args is not None
        audit_params = enqueue_audit.await_args.args[2]
        assert audit_params["action"] == "skill_bindings_advanced"
        assert audit_params["entity_type"] == "skill"
        assert audit_params["entity_id"] == skill_id
        assert audit_params["metadata"]["changes"] == {
            "personal_chat_revision_number": {"old": 1, "new": 2}
        }
        assert audit_params["metadata"]["extra"]["surface"] == "personal_chat"
        # Audit metadata carries identity and version facts, never content.
        assert "instructions" not in str(audit_params["metadata"])

        repeated = await client.post(
            f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
            json={
                "expected_pinned_revision_id": second_revision_id,
                "expected_published_revision_id": second_revision_id,
            },
            headers=headers,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["outcome"] == "already_current"
        assert repeated.json()["to_revision_number"] == 2
        assert enqueue_audit.await_count == 1

    policy_response = await client.get(
        "/api/v1/admin/governance-policy/",
        headers=headers,
    )
    assert policy_response.status_code == 200, policy_response.text
    bindings = policy_response.json()["skills"]["bindings"]
    assert [b["skill_revision_id"] for b in bindings] == [second_revision_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_move_the_governance_fit_rejects_rolls_back_unaudited(
    client, admin_token, db_container
):
    """The advance runs the same fit validation as a policy save.

    A published revision that no longer fits the personal default assistant's
    context must refuse the move, keep the old pin, and write no audit event.
    """
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with db_container() as container:
        await container.space_init_service().get_personal_space()

    create_response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"pin-advance-oversized-{uuid4().hex[:8]}",
            "display_name": "Pin advance oversized",
            "description": "Approved guidance.",
            "instructions": "Follow the approved instructions.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill_id = create_response.json()["id"]
    first_revision_id = create_response.json()["current_revision"]["id"]
    publish_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": first_revision_id},
        headers=headers,
    )
    assert publish_response.status_code == 200, publish_response.text
    bind_response = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "skills": {
                "bindings": [
                    {
                        "skill_id": skill_id,
                        "skill_revision_id": first_revision_id,
                    }
                ]
            }
        },
        headers=headers,
    )
    assert bind_response.status_code == 200, bind_response.text

    revision_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/revisions/",
        json={
            "display_name": "Pin advance oversized",
            "description": "Approved guidance, revised far beyond any budget.",
            "instructions": "overflow " * 10_000,
        },
        headers=headers,
    )
    assert revision_response.status_code == 201, revision_response.text
    second_revision_id = revision_response.json()["id"]
    republish_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": second_revision_id},
        headers=headers,
    )
    assert republish_response.status_code == 200, republish_response.text

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        refused = await client.post(
            f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
            json={
                "expected_pinned_revision_id": first_revision_id,
                "expected_published_revision_id": second_revision_id,
            },
            headers=headers,
        )
    assert refused.status_code == 400, refused.text
    assert "context window" in refused.json()["message"]
    assert enqueue_audit.await_count == 0

    policy_response = await client.get(
        "/api/v1/admin/governance-policy/",
        headers=headers,
    )
    assert policy_response.status_code == 200, policy_response.text
    bindings = policy_response.json()["skills"]["bindings"]
    assert [b["skill_revision_id"] for b in bindings] == [first_revision_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_publish_after_the_review_is_refused_not_silently_applied(
    client, admin_token, db_container
):
    """The administrator reviewed a move to version 2; version 3 was published
    before the call. The advance must refuse rather than move the tenant's
    Personal Chat to a revision nobody previewed."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with db_container() as container:
        await container.space_init_service().get_personal_space()

    create_response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"pin-advance-target-{uuid4().hex[:8]}",
            "display_name": "Pin advance target",
            "description": "Approved guidance.",
            "instructions": "Follow the approved instructions.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill_id = create_response.json()["id"]
    first_revision_id = create_response.json()["current_revision"]["id"]
    assert (
        await client.post(
            f"/api/v1/skills/organization/{skill_id}/publish/",
            json={"expected_revision_id": first_revision_id},
            headers=headers,
        )
    ).status_code == 200
    bind_response = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "skills": {
                "bindings": [
                    {"skill_id": skill_id, "skill_revision_id": first_revision_id}
                ]
            }
        },
        headers=headers,
    )
    assert bind_response.status_code == 200, bind_response.text

    reviewed_target = None
    for iteration in (2, 3):
        revision_response = await client.post(
            f"/api/v1/skills/organization/{skill_id}/revisions/",
            json={
                "display_name": "Pin advance target",
                "description": f"Approved guidance, revision {iteration}.",
                "instructions": f"Follow approved revision {iteration}.",
            },
            headers=headers,
        )
        assert revision_response.status_code == 201, revision_response.text
        publish_response = await client.post(
            f"/api/v1/skills/organization/{skill_id}/publish/",
            json={"expected_revision_id": revision_response.json()["id"]},
            headers=headers,
        )
        assert publish_response.status_code == 200, publish_response.text
        if iteration == 2:
            reviewed_target = revision_response.json()["id"]

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        refused = await client.post(
            f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
            json={
                "expected_pinned_revision_id": first_revision_id,
                "expected_published_revision_id": reviewed_target,
            },
            headers=headers,
        )
    assert refused.status_code == 409, refused.text
    assert enqueue_audit.await_count == 0

    policy_response = await client.get(
        "/api/v1/admin/governance-policy/",
        headers=headers,
    )
    assert policy_response.status_code == 200, policy_response.text
    bindings = policy_response.json()["skills"]["bindings"]
    assert [b["skill_revision_id"] for b in bindings] == [first_revision_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unpublished_and_blocked_refusals_carry_their_own_codes(
    client, admin_token, db_container
):
    """SDK and localized UI consumers pick recovery from the stable code:
    9053 means publish the Skill first, 9054 means clear the execution
    block. Neither may collapse into the generic BAD_REQUEST contract."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with db_container() as container:
        await container.space_init_service().get_personal_space()

    create_response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"pin-advance-codes-{uuid4().hex[:8]}",
            "display_name": "Pin advance codes",
            "description": "Approved guidance.",
            "instructions": "Follow the approved instructions.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill_id = create_response.json()["id"]
    first_revision_id = create_response.json()["current_revision"]["id"]

    # Never published: the advance names the publication gap.
    not_published = await client.post(
        f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
        json={
            "expected_pinned_revision_id": first_revision_id,
            "expected_published_revision_id": first_revision_id,
        },
        headers=headers,
    )
    assert not_published.status_code == 400, not_published.text
    assert not_published.json()["eneo_error_code"] == 9053

    # Published, bound, then blocked: the advance names the block.
    assert (
        await client.post(
            f"/api/v1/skills/organization/{skill_id}/publish/",
            json={"expected_revision_id": first_revision_id},
            headers=headers,
        )
    ).status_code == 200
    bind_response = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "skills": {
                "bindings": [
                    {"skill_id": skill_id, "skill_revision_id": first_revision_id}
                ]
            }
        },
        headers=headers,
    )
    assert bind_response.status_code == 200, bind_response.text
    block_response = await client.post(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        json={"reason": "Confirmed unsafe instructions"},
        headers=headers,
    )
    assert block_response.status_code in (200, 201), block_response.text

    blocked = await client.post(
        f"/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
        json={
            "expected_pinned_revision_id": first_revision_id,
            "expected_published_revision_id": first_revision_id,
        },
        headers=headers,
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["eneo_error_code"] == 9054
