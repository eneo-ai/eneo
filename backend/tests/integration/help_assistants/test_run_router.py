"""HTTP integration tests for the helper-run router (step 022).

Pins the wiring contract for ``/api/v1/help-assistants/runs/...``:

  * ``POST /runs/`` succeeds when the caller can edit the target assistant
    and the active role for the requested ``kind`` is enabled.
  * ``POST /runs/`` returns 403 when the caller cannot edit the target.
  * ``POST /runs/`` returns 403 when the active role is disabled
    (``helper_not_available``).
  * ``POST /runs/{run_id}/turns/`` returns 200 for the original actor and
    403 for any other user in the same tenant.
  * ``PATCH /runs/{run_id}/`` rejects a second terminal transition with 400
    — once a run is completed/abandoned/failed, the row is final.
  * Streaming smoke: ``stream=true`` returns a ``text/event-stream`` body
    containing the stubbed chunk text.

The completion call is stubbed via monkeypatch — the deep streaming
contract (token accounting, provider chunking) is tested at the
completion-service layer; here we verify the SSE wire-format only.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


_STUB_ANSWER = "Helper would say something polite here."


# ---------------------------------------------------------------------------
# Stubs — completion service responses
# ---------------------------------------------------------------------------


def _non_stream_response(
    *, model: Any, captured: dict[str, Any]
) -> CompletionModelResponse:
    captured["extended_logging"] = captured.get("extended_logging")  # touch
    return CompletionModelResponse(
        completion=Completion(text=_STUB_ANSWER, response_type=ResponseType.TEXT),
        model=model,
        extended_logging=None,
        total_token_count=42,
        usage=None,
    )


def _stream_response(
    *, model: Any, captured: dict[str, Any]
) -> CompletionModelResponse:
    """Yield two TEXT chunks then stop — enough to verify SSE framing.

    A non-string ``completion`` (here: an async generator) is what
    ``EventSourceResponse`` iterates inside the router.
    """

    async def _gen() -> AsyncGenerator[Completion, None]:
        yield Completion(response_type=ResponseType.TEXT, text="Hello ")
        yield Completion(response_type=ResponseType.TEXT, text="world.")

    return CompletionModelResponse(
        completion=_gen(),
        model=model,
        extended_logging=None,
        total_token_count=42,
        usage=None,
    )


@pytest.fixture
def stub_completion_service(monkeypatch):
    """Monkeypatch ``CompletionService.get_response`` to return stubs.

    Captures ``stream`` so each test can assert which branch the router
    exercised. The captured ``extended_logging`` value is also recorded
    so the streaming branch keeps Critical test #3's invariant — even
    though the dedicated test in ``test_helper_run_no_extended_logging``
    pins the non-stream branch.
    """

    captured: dict[str, Any] = {}

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        captured["stream"] = kwargs.get("stream")
        captured["extended_logging"] = kwargs.get("extended_logging")
        model = kwargs.get("model")
        if kwargs.get("stream"):
            return _stream_response(model=model, captured=captured)
        return _non_stream_response(model=model, captured=captured)

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)
    return captured


# ---------------------------------------------------------------------------
# DB / fixture helpers — mirror neighbouring test files
# ---------------------------------------------------------------------------


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None, "Expected an org-space seeded by add_tenant_user"
    return row


async def _get_default_completion_model_id(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    assert row is not None, "Expected seed_default_models to provide a model"
    return row


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
    completion_model_id: UUID,
    name: str,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=completion_model_id,
            logging_enabled=False,
            is_default=False,
            published=False,
        )
    )
    return assistant_id


async def _assign_helper_role(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
    is_enabled: bool = True,
) -> None:
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    role = factory.create_role_assignment(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        created_by_user_id=actor_user_id,
    )
    role.is_enabled = is_enabled
    await role_repo.add(role)


async def _seed_helper_and_target(
    container,
    admin_user,
    *,
    role_enabled: bool = True,
) -> tuple[UUID, UUID]:
    """Insert helper + target assistants and the active role assignment.

    Returns ``(helper_assistant_id, target_assistant_id)``.
    """
    space_service = container.space_service()
    await space_service.get_or_create_tenant_space()

    session = container.session()
    org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
    completion_model_id = await _get_default_completion_model_id(
        session, tenant_id=admin_user.tenant_id
    )
    helper_id = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=org_space_id,
        completion_model_id=completion_model_id,
        name="prompt-guide-helper",
    )
    target_id = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=org_space_id,
        completion_model_id=completion_model_id,
        name="target-assistant",
    )
    await _assign_helper_role(
        container,
        org_space_id=org_space_id,
        assistant_id=helper_id,
        actor_user_id=admin_user.id,
        is_enabled=role_enabled,
    )
    await session.flush()
    return helper_id, target_id


async def _create_member_target(db_container, member_user) -> UUID:
    """A target assistant a non-admin member owns and can edit (personal space).

    The real end-user flow (PRD §11): the user creates an assistant in their own
    personal space, where ``space_actor._get_role`` resolves them to ``OWNER``
    (they also need the tenant-level ``assistants`` permission — see the
    ``member_*`` fixtures). ``_seed_helper_and_target`` puts its target in the
    admin-owned org-space, so a non-admin never passed the target-edit gate here
    — the run's *helper* read 403 (step 099) was therefore never reached.
    """
    async with db_container(user=member_user) as container:
        space_service = container.space_service()
        personal_space = await space_service.create_personal_space()
        session = container.session()
        completion_model_id = await _get_default_completion_model_id(
            session, tenant_id=member_user.tenant_id
        )
        target_id = await _insert_assistant(
            session,
            owner_user_id=member_user.id,
            space_id=personal_space.id,
            completion_model_id=completion_model_id,
            name="member-personal-target",
        )
        await session.flush()
    return target_id


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def non_admin_role(db_container, admin_user):
    async with db_container() as container:
        role_repo = container.role_repo()
        return await role_repo.create_role(
            RoleCreate(
                name=f"non-admin-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )


@pytest.fixture
async def non_admin_user(db_container, admin_user, non_admin_role):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.add(
            UserAdd(
                email=f"non-admin-{uuid4().hex[:8]}@example.com",
                username=f"non_admin_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=non_admin_role.id)],
            )
        )


@pytest.fixture
async def non_admin_token(db_container, patch_auth_service_jwt, non_admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(non_admin_user)


@pytest.fixture
async def member_role(db_container, admin_user):
    """A non-admin "Member" role: the ordinary ``assistants`` capability, no
    ``admin``. Matches the repro's Member role — enough to create/edit one's
    own assistants, but not an org-space member.
    """
    async with db_container() as container:
        role_repo = container.role_repo()
        return await role_repo.create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS],
                tenant_id=admin_user.tenant_id,
            )
        )


@pytest.fixture
async def member_user(db_container, admin_user, member_role):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=member_role.id)],
            )
        )


@pytest.fixture
async def member_token(db_container, patch_auth_service_jwt, member_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(member_user)


# ---------------------------------------------------------------------------
# Tests — start
# ---------------------------------------------------------------------------


async def test_start_run_succeeds_when_caller_can_edit_target(
    client,
    db_container,
    admin_user,
    admin_token,
    stub_completion_service,
):
    """Edit-permitted caller → 200, body carries run + answer + references."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Help me write a system prompt.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == _STUB_ANSWER
    assert body["run"]["kind"] == HelperKind.PROMPT_GUIDE.value
    assert body["run"]["target_id"] == str(target_id)
    assert body["run"]["target_type"] == "assistant"
    assert body["run"]["actor_user_id"] == str(admin_user.id)
    assert body["run"]["status"] == "in_progress"
    assert body["run"]["id"]
    assert stub_completion_service["stream"] is False


async def test_start_run_returns_403_when_caller_cannot_edit_target(
    client,
    db_container,
    admin_user,
    non_admin_user,  # noqa: ARG001 — token fixture builds against this user
    non_admin_token,
    stub_completion_service,
):
    """Non-admin (no org-space membership) cannot reach the target → 403.

    The tenant-admin seed adds ``admin_user`` to the org-space via
    ``get_or_create_tenant_space``. A freshly-created non-admin user with
    no role permissions is **not** a member, so
    ``assistant_service.get_assistant`` raises an ``UnauthorizedException``
    that surfaces as 403. This proves the router relays the service's
    permission failure rather than swallowing it.
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {non_admin_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Should not be allowed.",
        },
    )
    assert resp.status_code == 403, resp.text


async def test_start_run_returns_403_when_role_disabled(
    client,
    db_container,
    admin_user,
    admin_token,
    stub_completion_service,
):
    """Disabled role → 403 with ``helper_not_available`` (PRD §5)."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(
            container, admin_user, role_enabled=False
        )

    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Help me.",
        },
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # ``UnauthorizedException(code="helper_not_available", ...)`` surfaces
    # in the JSON body as ``code`` + ``message`` (see exception_handlers).
    # An operator distinguishing this 403 from a permission failure should
    # be able to do so without parsing the human-readable message.
    assert body.get("code") == "helper_not_available", body


async def test_non_admin_can_run_on_own_target(
    client,
    db_container,
    admin_user,
    member_user,
    member_token,
    stub_completion_service,
):
    """Non-admin who can edit their own target runs the Prompt Guide → 200.

    Step 099 regression. The run path loaded the org-space helper through the
    permission-enforcing ``get_assistant``, so a non-admin (never an org-space
    member) 403'd on the *helper* read even after clearing the target-edit
    gate. With the privileged helper load the run gets past that read; the
    completion is stubbed, so a 200 + answer proves the authorization rather
    than the LLM. The run is stamped to the non-admin actor. PRD §5/§6/§10.
    """
    async with db_container() as container:
        await _seed_helper_and_target(container, admin_user)
    target_id = await _create_member_target(db_container, member_user)

    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Help me write a system prompt.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == _STUB_ANSWER
    assert body["run"]["actor_user_id"] == str(member_user.id)
    assert body["run"]["target_id"] == str(target_id)
    assert body["run"]["status"] == "in_progress"
    assert stub_completion_service["stream"] is False


# ---------------------------------------------------------------------------
# Tests — follow-up
# ---------------------------------------------------------------------------


async def _start_run_and_get_id(client, *, admin_token, target_id: UUID) -> UUID:
    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Initial question.",
        },
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["run"]["id"])


async def test_followup_succeeds_for_original_actor(
    client,
    db_container,
    admin_user,
    admin_token,
    stub_completion_service,
):
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    run_id = await _start_run_and_get_id(
        client, admin_token=admin_token, target_id=target_id
    )

    resp = await client.post(
        f"/api/v1/help-assistants/runs/{run_id}/turns/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"question": "Follow-up question."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == _STUB_ANSWER
    assert body["run"]["id"] == str(run_id)


async def test_followup_returns_403_for_different_user(
    client,
    db_container,
    admin_user,
    admin_token,
    non_admin_token,
    stub_completion_service,
):
    """A second user in the same tenant cannot append to another's run.

    Tenant-scoped: same tenant means the run is found, so the actor check
    raises 403 (not 404).
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    run_id = await _start_run_and_get_id(
        client, admin_token=admin_token, target_id=target_id
    )

    resp = await client.post(
        f"/api/v1/help-assistants/runs/{run_id}/turns/",
        headers={"Authorization": f"Bearer {non_admin_token}"},
        json={"question": "Should not be allowed."},
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Tests — status transitions
# ---------------------------------------------------------------------------


async def test_double_complete_is_rejected(
    client,
    db_container,
    admin_user,
    admin_token,
    stub_completion_service,
):
    """First ``PATCH status=completed`` succeeds; the second returns 400."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    run_id = await _start_run_and_get_id(
        client, admin_token=admin_token, target_id=target_id
    )

    resp = await client.patch(
        f"/api/v1/help-assistants/runs/{run_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "completed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"
    assert resp.json()["completed_at"] is not None

    resp2 = await client.patch(
        f"/api/v1/help-assistants/runs/{run_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "completed"},
    )
    assert resp2.status_code == 400, resp2.text


# ---------------------------------------------------------------------------
# Tests — SSE smoke
# ---------------------------------------------------------------------------


async def test_stream_response_yields_sse_chunks(
    client,
    db_container,
    admin_user,
    admin_token,
    stub_completion_service,
):
    """``stream=true`` returns ``text/event-stream`` with the stubbed chunks.

    Body smoke: parse SSE ``data:`` lines and verify the helper's answer
    text appears in the payloads. The deep streaming contract (token
    accounting, provider chunking) is tested at the completion-service
    layer.
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    resp = await client.post(
        "/api/v1/help-assistants/runs/",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "kind": HelperKind.PROMPT_GUIDE.value,
            "target_type": "assistant",
            "target_id": str(target_id),
            "question": "Stream please.",
            "stream": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert stub_completion_service["stream"] is True

    chunks: list[str] = []
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            chunks.append(data.get("answer", ""))

    assert chunks, "Expected at least one SSE data chunk"
    joined = "".join(chunks)
    # Two stub chunks: "Hello " + "world." — both must reach the wire.
    assert "Hello " in joined
    assert "world." in joined
