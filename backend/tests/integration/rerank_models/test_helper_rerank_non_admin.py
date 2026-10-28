"""A help assistant's reranker resolves for an ordinary member, not only for admins.

The helper lives in the org space, whose only members are tenant admins.
Helper runs therefore load it through a privileged read; resolving its
reranker must not fall back to the permission-enforcing space read, or every
non-admin run of a helper with a reranker would fail.
"""

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.main.models import ModelId
from eneo.rerank_models.application.rerank_service import RerankService
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def member_user(db_container, admin_user):
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS],
                tenant_id=admin_user.tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


async def _seed_helper_with_reranker(container, admin_user, reranker_id):
    await container.space_service().get_or_create_tenant_space()
    session = container.session()
    org_space_id = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == admin_user.tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    completion_model_id = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == admin_user.tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    helper_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=helper_id,
            name="prompt-guide-helper",
            user_id=admin_user.id,
            space_id=org_space_id,
            completion_model_id=completion_model_id,
            rerank_model_id=reranker_id,
            logging_enabled=False,
            is_default=False,
            published=False,
        )
    )
    factory = container.helper_assistants_factory()
    await container.org_space_assistant_role_repo().add(
        factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=helper_id,
            is_enabled=True,
            is_visible_to_users=True,
            created_by_user_id=admin_user.id,
        )
    )
    await session.flush()
    return helper_id


async def test_member_resolves_the_helpers_reranker(
    db_container, admin_user, member_user, rerank_model_factory, monkeypatch
):
    # The factory's provider has a placeholder key; the provider call is not
    # what this test is about, so the reranker it would build is stubbed.
    async def stub_reranker(self, model):  # noqa: ARG001
        return object()

    monkeypatch.setattr(RerankService, "_reranker", stub_reranker)

    async with db_container() as container:
        reranker = await rerank_model_factory(container.session(), "helper-reranker")
        helper_id = await _seed_helper_with_reranker(container, admin_user, reranker.id)

    async with db_container(user=member_user) as container:
        helper = await container.assistant_service().get_help_assistant(helper_id)
        spec = await container.helper_run_service()._rerank_for(
            helper, "Vad kostar det?"
        )

    assert spec is not None
    assert spec.query == "Vad kostar det?"
