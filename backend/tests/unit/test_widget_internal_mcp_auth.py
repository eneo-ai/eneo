"""Exercise visitor delegation through the real internal knowledge-tool boundary."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt
import pytest
from dependency_injector import providers
from mcp.server.fastmcp import Context
from starlette.requests import Request

from eneo.authentication.auth_models import WIDGET_MCP_AUDIENCE
from eneo.authentication.auth_service import AuthService
from eneo.internal_mcp.foundation import (
    internal_tool_context,
    mcp_server_id_from_token,
    scoped_claims_from_token,
)
from eneo.internal_mcp.knowledge import search_knowledge
from eneo.main.config import get_settings
from eneo.main.container import container as container_module
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService
from eneo.widgets.application.visitor_token_service import VisitorTokenService
from eneo.widgets.application.visitor_user import build_visitor_user
from eneo.widgets.application.widget_authentication_service import (
    WidgetAuthenticationService,
)
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    VisitorTokenStaleError,
    WidgetNotActiveError,
)
from eneo.widgets.domain.widget import Widget, WidgetStatus


@dataclass
class WidgetAuthCase:
    widget: Widget
    tenant: TenantInDB
    user: UserInDB
    service: WidgetAuthenticationService
    widget_repo: MagicMock
    tenant_repo: MagicMock
    user_service: UserService

    def token(self, *, expires_in: int = 15) -> str:
        return AuthService().create_scoped_mcp_token(
            self.user, assistant_id=self.widget.target_id, expires_in=expires_in
        )


@pytest.fixture
def case() -> WidgetAuthCase:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="Coffee"
    ).model_copy(update={"id": uuid4(), "status": WidgetStatus.ACTIVE})
    tenant = TenantInDB(id=widget.tenant_id, name="Demo", quota_limit=0)
    user = build_visitor_user(widget, uuid4(), tenant)
    widget_repo = MagicMock()
    widget_repo.get = AsyncMock(return_value=widget)
    widget_repo.get_by_public_id = AsyncMock(return_value=widget)
    widget_repo.is_target_published = AsyncMock(return_value=True)
    tenant_repo = MagicMock()
    tenant_repo.get = AsyncMock(return_value=tenant)
    user_repo = MagicMock()
    user_repo.get_user_by_username = AsyncMock(return_value=None)
    user_service = UserService(
        user_repo=user_repo,
        auth_service=AuthService(),
        api_key_auth_resolver=MagicMock(),
        api_key_v2_repo=MagicMock(),
        audit_service=None,
        settings_repo=MagicMock(),
        tenant_repo=tenant_repo,
        info_blob_repo=MagicMock(),
    )
    service = WidgetAuthenticationService(
        widget_repo, tenant_repo, user_service, VisitorTokenService()
    )
    return WidgetAuthCase(
        widget, tenant, user, service, widget_repo, tenant_repo, user_service
    )


def _ctx(token: str) -> Context:
    ctx = MagicMock(spec=Context)
    ctx.request_context.request = Request(
        {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
    )
    return ctx


def _resign(token: str, **changes: object) -> str:
    settings = get_settings()
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=WIDGET_MCP_AUDIENCE,
    )
    claims.update(changes)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
def tool_container(case: WidgetAuthCase, monkeypatch: pytest.MonkeyPatch) -> Container:
    container = Container()
    container.widget_repo.override(providers.Object(case.widget_repo))
    container.tenant_repo.override(providers.Object(case.tenant_repo))
    container.user_service.override(providers.Object(case.user_service))
    monkeypatch.setattr(container_module, "Container", lambda **_: container)

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(begin=transaction)

    monkeypatch.setattr("eneo.internal_mcp.foundation.sessionmanager.session", session)
    return container


async def test_demo_search_returns_knowledge_without_a_user_row(
    case: WidgetAuthCase, tool_container: Container
):
    collection = SimpleNamespace(id=uuid4(), embedding_model=SimpleNamespace())
    assistant = SimpleNamespace(
        collections=[collection], websites=[], integration_knowledge_list=[]
    )
    tool_container.assistant_service.override(
        providers.Object(
            SimpleNamespace(get_assistant=AsyncMock(return_value=(assistant, [])))
        )
    )
    tool_container.datastore.override(
        providers.Object(
            SimpleNamespace(
                semantic_search=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            info_blob_id=uuid4(),
                            info_blob_title="Coffee guide",
                            chunk_no=0,
                            text="Use freshly ground coffee.",
                            score=0.9,
                        )
                    ]
                )
            )
        )
    )
    tool_container.info_blob_chunk_repo.override(
        providers.Object(
            SimpleNamespace(get_adjacent_chunks=AsyncMock(return_value=[]))
        )
    )

    content = await search_knowledge(
        "bryggning kaffe hemma metoder", _ctx(case.token())
    )

    assert content[0].type == "text" and "1 result(s)" in content[0].text
    assert content[1].type == "resource"
    assert "Use freshly ground coffee." in content[1].resource.text
    resolved = tool_container.user()
    assert resolved.id == case.user.id
    assert resolved.permissions == set()
    assert resolved.active_widget == case.user.active_widget


def test_widget_delegation_cannot_authenticate_to_normal_api(case: WidgetAuthCase):
    with pytest.raises(AuthenticationException):
        AuthService().get_jwt_payload(case.token(), key=get_settings().jwt_secret)


def test_public_visitor_token_cannot_call_internal_tools(case: WidgetAuthCase):
    token, _ = VisitorTokenService().mint(case.widget, case.user.id)
    with pytest.raises(AuthenticationException):
        scoped_claims_from_token(token)


def test_delegation_cannot_be_minted_for_another_assistant(case: WidgetAuthCase):
    with pytest.raises(ValueError, match="widget's assistant"):
        AuthService().create_scoped_mcp_token(case.user, assistant_id=uuid4())


def test_builtin_provider_scope_survives_delegation(case: WidgetAuthCase):
    server_id = uuid4()
    token = AuthService().create_scoped_mcp_token(
        case.user, assistant_id=case.widget.target_id, mcp_server_id=server_id
    )
    assert mcp_server_id_from_token(token) == server_id


@pytest.mark.parametrize(
    "failure",
    ["expired", "signature", "wrong_audience", "missing_scope", "account_audience"],
)
def test_invalid_credentials_are_rejected(case: WidgetAuthCase, failure: str):
    token = case.token()
    if failure == "expired":
        token = case.token(expires_in=-1)
    elif failure == "signature":
        head, payload, signature = token.split(".")
        token = ".".join(
            (head, payload, ("A" if signature[0] != "A" else "B") + signature[1:])
        )
    elif failure == "wrong_audience":
        token = _resign(token, aud="some-other-service")
    elif failure == "missing_scope":
        token = _resign(token, widget_visitor=None)
    else:
        token = _resign(token, aud=get_settings().jwt_audience)
    with pytest.raises(AuthenticationException):
        scoped_claims_from_token(token)


@pytest.mark.parametrize(
    "failure",
    [
        "tenant",
        "space",
        "target",
        "assistant",
        "missing",
        "generation",
        "paused",
        "archived",
        "draft",
        "unpublished",
        "suspended",
    ],
)
async def test_live_revocation_and_scope_checks_at_tool_boundary(
    case: WidgetAuthCase, tool_container: Container, failure: str
):
    token = case.token()
    expected = WidgetNotActiveError
    if failure in {"tenant", "space", "target"}:
        case.widget_repo.get.return_value = case.widget.model_copy(
            update={f"{failure}_id": uuid4()}
        )
        expected = VisitorTokenInvalidError
    elif failure == "assistant":
        token = _resign(token, assistant_id=str(uuid4()))
        expected = VisitorTokenInvalidError
    elif failure == "missing":
        case.widget_repo.get.return_value = None
    elif failure == "generation":
        case.widget_repo.get.return_value = case.widget.model_copy(
            update={"token_generation": 1}
        )
        expected = VisitorTokenStaleError
    elif failure in {"paused", "archived", "draft"}:
        case.widget_repo.get.return_value = case.widget.model_copy(
            update={"status": WidgetStatus(failure)}
        )
    elif failure == "unpublished":
        case.widget_repo.is_target_published.return_value = False
    elif failure == "suspended":
        case.tenant_repo.get.return_value = case.tenant.model_copy(
            update={"state": TenantState.SUSPENDED}
        )
    with pytest.raises(expected):
        async with internal_tool_context(_ctx(token)):
            pytest.fail("Invalid visitor reached the tool")


async def test_preview_survives_delegation_but_cannot_revive_archived_widget(
    case: WidgetAuthCase,
):
    case.user = build_visitor_user(case.widget, case.user.id, case.tenant, preview=True)
    claims = scoped_claims_from_token(case.token())
    assert claims.widget_visitor is not None
    case.widget_repo.get.return_value = case.widget.model_copy(
        update={"status": WidgetStatus.DRAFT}
    )
    user = await case.service.authenticate_internal(
        claims.widget_visitor, assistant_id=claims.assistant_id
    )
    assert user.active_widget is not None and user.active_widget.preview is True
    case.widget_repo.get.return_value = case.widget.model_copy(
        update={"status": WidgetStatus.ARCHIVED}
    )
    with pytest.raises(WidgetNotActiveError):
        await case.service.authenticate_internal(
            claims.widget_visitor, assistant_id=claims.assistant_id
        )


async def test_normal_account_still_uses_existing_authentication(
    case: WidgetAuthCase, tool_container: Container
):
    account = case.user.model_copy(update={"active_widget": None})
    token = AuthService().create_scoped_mcp_token(
        account, assistant_id=case.widget.target_id
    )
    assert scoped_claims_from_token(token).widget_visitor is None
    case.user_service.repo.get_user_by_username.return_value = account
    async with internal_tool_context(_ctx(token)) as context:
        assert context.user is account
        assert context.user.active_widget is None


@pytest.mark.parametrize(
    "status", [WidgetStatus.DRAFT, WidgetStatus.PAUSED, WidgetStatus.ARCHIVED]
)
async def test_public_and_internal_calls_share_widget_lifecycle(
    case: WidgetAuthCase, status: WidgetStatus
):
    widget = case.widget.model_copy(update={"status": status})
    case.widget_repo.get_by_public_id.return_value = widget
    with pytest.raises(WidgetNotActiveError):
        await case.service.get_active_widget(widget.public_id)
    preview_token, _ = VisitorTokenService().mint(widget, case.user.id, preview=True)
    if status == WidgetStatus.ARCHIVED:
        with pytest.raises(WidgetNotActiveError):
            await case.service.get_active_widget(
                widget.public_id, preview_token=preview_token
            )
    else:
        assert (
            await case.service.get_active_widget(
                widget.public_id, preview_token=preview_token
            )
            == widget
        )


async def test_public_widget_rejects_unpublished_assistant(case: WidgetAuthCase):
    case.widget_repo.is_target_published.return_value = False
    with pytest.raises(WidgetNotActiveError):
        await case.service.get_active_widget(case.widget.public_id)


async def test_resolved_visitor_uses_live_retention_policy(case: WidgetAuthCase):
    from eneo.widgets.domain.widget import WidgetPrivacy

    claims = scoped_claims_from_token(case.token())
    assert claims.widget_visitor is not None
    case.widget_repo.get.return_value = case.widget.model_copy(
        update={"privacy": WidgetPrivacy(retention_days=0)}
    )
    user = await case.service.authenticate_internal(
        claims.widget_visitor, assistant_id=claims.assistant_id
    )
    assert user.active_widget is not None and user.active_widget.never_persist is True


async def test_old_account_shaped_visitor_token_fails_with_original_error(
    case: WidgetAuthCase, tool_container: Container
):
    token = AuthService().create_access_token_for_user(
        case.user, extra_claims={"assistant_id": str(case.widget.target_id)}
    )
    with pytest.raises(AuthenticationException, match="No authenticated user"):
        async with internal_tool_context(_ctx(token)):
            pytest.fail("Synthetic username authenticated as an account")


async def test_public_preview_identity_reaches_internal_tools(
    case: WidgetAuthCase, tool_container: Container
):
    from eneo.server.dependencies.widget_auth import (
        get_active_widget,
        get_visitor_container,
        get_widget_principal,
    )

    widget = case.widget.model_copy(update={"status": WidgetStatus.DRAFT})
    case.widget_repo.get_by_public_id.return_value = widget
    case.widget_repo.get.return_value = widget
    public_token, _ = VisitorTokenService().mint(widget, case.user.id, preview=True)
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {public_token}".encode())],
        }
    )
    active = await get_active_widget(request, widget.public_id, tool_container)
    principal = await get_widget_principal(request, active, tool_container)
    await get_visitor_container(request, principal, tool_container)
    delegated = AuthService().create_scoped_mcp_token(
        tool_container.user(), assistant_id=widget.target_id
    )
    async with internal_tool_context(_ctx(delegated)) as context:
        assert context.user.active_widget is not None
        assert context.user.active_widget.preview is True
        assert context.user.id == principal.visitor_id
        assert context.assistant_id == widget.target_id
