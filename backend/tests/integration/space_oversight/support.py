"""Setup shared by the tenant-admin space oversight integration tests.

Rows the oversight read model aggregates are inserted with SQL, so each test
controls exactly who is a member, in which state and through which group.
Everything the tests act on goes through the HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState
from eneo.widgets.domain.widget import generate_public_id

ADMIN_EMAIL = "test@example.com"
REASON = "Ärende KS 2026/123 – kontroll av underlag"
ORIGIN = "https://www.kommun.se"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def key(secret: str) -> dict[str, str]:
    return {"X-API-Key": secret}


@dataclass(frozen=True)
class Person:
    id: UUID
    email: str
    username: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.token)


async def new_person(
    db_container: Any,
    permissions: list[Permission],
    *,
    label: str = "person",
    tenant_id: Optional[UUID] = None,
) -> Person:
    """A signed-in user with a role holding ``permissions`` (none when
    empty), in the seeded tenant unless ``tenant_id`` says otherwise."""
    async with db_container() as container:
        if tenant_id is None:
            admin = await container.user_repo().get_user_by_email(ADMIN_EMAIL)
            tenant_id = admin.tenant_id
        roles: list[ModelId] = []
        if permissions:
            role = await container.role_repo().create_role(
                RoleCreate(
                    name=f"{label}-{uuid4().hex[:8]}",
                    permissions=permissions,
                    tenant_id=tenant_id,
                )
            )
            roles = [ModelId(id=role.id)]
        suffix = uuid4().hex[:8]
        user = await container.user_repo().add(
            UserAdd(
                email=f"{label}-{suffix}@example.com",
                username=f"{label}_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
                roles=roles,
            )
        )
        token = container.auth_service().create_access_token_for_user(user)
        return Person(
            id=user.id, email=user.email, username=user.username or "", token=token
        )


async def seeded_admin(db_container: Any) -> Person:
    """The seeded tenant admin (all predefined permissions, widgets too)."""
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(ADMIN_EMAIL)
        token = container.auth_service().create_access_token_for_user(user)
        return Person(
            id=user.id, email=user.email, username=user.username or "", token=token
        )


# --- SQL ----------------------------------------------------------------------


async def execute(statement: str, **params: Any) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(sa.text(statement), params)


async def fetch(statement: str, **params: Any) -> list[sa.Row[Any]]:
    async with sessionmanager.session() as session, session.begin():
        return list((await session.execute(sa.text(statement), params)).all())


async def scalar(statement: str, **params: Any) -> Any:
    async with sessionmanager.session() as session, session.begin():
        return (await session.execute(sa.text(statement), params)).scalar()


async def admin_row() -> tuple[UUID, UUID]:
    """(user id, tenant id) of the seeded tenant admin who creates spaces."""
    row = (
        await fetch("SELECT id, tenant_id FROM users WHERE email = :e", e=ADMIN_EMAIL)
    )[0]
    return row[0], row[1]


async def hub_id(tenant_id: UUID) -> UUID:
    hub = await scalar(
        "SELECT id FROM spaces WHERE tenant_id = :t AND user_id IS NULL"
        " AND tenant_space_id IS NULL",
        t=tenant_id,
    )
    if hub is None:
        hub = uuid4()
        await execute(
            "INSERT INTO spaces (id, name, tenant_id) VALUES (:id, 'Organisation', :t)",
            id=hub,
            t=tenant_id,
        )
    return hub


async def insert_tenant() -> UUID:
    tenant_id = uuid4()
    await execute(
        "INSERT INTO tenants (id, name, quota_limit, state)"
        " VALUES (:id, :name, 1000000, 'active')",
        id=tenant_id,
        name=f"other-{tenant_id.hex[:8]}",
    )
    return tenant_id


async def insert_user(
    tenant_id: UUID,
    *,
    state: str = "active",
    deleted: bool = False,
    label: str = "member",
) -> UUID:
    user_id = uuid4()
    await execute(
        "INSERT INTO users (id, tenant_id, username, email, used_tokens, state,"
        " deleted_at) VALUES (:id, :t, :u, :e, 0, :s, :d)",
        id=user_id,
        t=tenant_id,
        u=f"{label}_{user_id.hex[:8]}",
        e=f"{label}-{user_id.hex[:8]}@example.com",
        s=state,
        d=datetime.now(timezone.utc) if deleted else None,
    )
    return user_id


async def insert_space(
    tenant_id: UUID,
    *,
    name: Optional[str] = None,
    kind: str = "shared",
    owner_id: Optional[UUID] = None,
) -> UUID:
    """A space row without the aggregate's side effects (no default
    assistant, no models): what a never-opened space looks like."""
    space_id = uuid4()
    parent = await hub_id(tenant_id) if kind == "shared" else None
    await execute(
        "INSERT INTO spaces (id, name, tenant_id, tenant_space_id, user_id)"
        " VALUES (:id, :name, :t, :parent, :owner)",
        id=space_id,
        name=name or f"space-{space_id.hex[:8]}",
        t=tenant_id,
        parent=parent,
        owner=owner_id if kind == "personal" else None,
    )
    return space_id


async def add_member(
    space_id: UUID | str,
    user_id: UUID | str,
    role: str,
    *,
    created_at: Optional[datetime] = None,
) -> None:
    await execute(
        "INSERT INTO spaces_users (space_id, user_id, role, created_at, updated_at)"
        " VALUES (:s, :u, :r, :c, :c)",
        s=str(space_id),
        u=str(user_id),
        r=role,
        c=created_at or datetime.now(timezone.utc),
    )


async def insert_group(
    tenant_id: UUID,
    member_ids: list[UUID],
    *,
    name: Optional[str] = None,
    state: Optional[str] = None,
) -> UUID:
    group_id = uuid4()
    await execute(
        "INSERT INTO user_groups (id, name, tenant_id, state) VALUES (:id, :n, :t, :s)",
        id=group_id,
        n=name or f"group-{group_id.hex[:8]}",
        t=tenant_id,
        s=state,
    )
    for user_id in member_ids:
        await execute(
            "INSERT INTO usergroups_users (user_id, user_group_id) VALUES (:u, :g)",
            u=user_id,
            g=group_id,
        )
    return group_id


async def add_group(space_id: UUID | str, group_id: UUID, role: str) -> None:
    await execute(
        "INSERT INTO spaces_user_groups (space_id, user_group_id, role)"
        " VALUES (:s, :g, :r)",
        s=str(space_id),
        g=group_id,
        r=role,
    )


async def member_row(
    space_id: UUID | str, user_id: UUID | str
) -> Optional[sa.Row[Any]]:
    rows = await fetch(
        "SELECT role, oversight_joined_at, oversight_join_reason, created_at"
        " FROM spaces_users WHERE space_id = :s AND user_id = :u",
        s=str(space_id),
        u=str(user_id),
    )
    return rows[0] if rows else None


async def audit_rows(
    *, action: Optional[str] = None, entity_id: Optional[UUID | str] = None
) -> list[dict[str, Any]]:
    """Audit entries of space oversight and widget actions (the seeder's
    own entries are left out), oldest first."""
    rows = await fetch(
        "SELECT action, entity_id, actor_id, description, metadata FROM audit_logs"
        " WHERE (action LIKE 'space_oversight_%' OR action LIKE 'widget_%')"
        " AND (CAST(:a AS text) IS NULL OR action = :a)"
        " AND (CAST(:e AS uuid) IS NULL OR entity_id = CAST(:e AS uuid))"
        " ORDER BY timestamp, id",
        a=action,
        e=str(entity_id) if entity_id is not None else None,
    )
    return [
        {
            "action": row[0],
            "entity_id": row[1],
            "actor_id": row[2],
            "description": row[3],
            "metadata": row[4],
        }
        for row in rows
    ]


async def insert_assistant(
    space_id: UUID | str,
    owner_id: UUID,
    *,
    name: Optional[str] = None,
    published: bool = False,
    is_default: bool = False,
) -> UUID:
    assistant_id = uuid4()
    await execute(
        "INSERT INTO assistants (id, name, user_id, space_id, logging_enabled,"
        " is_default, published, type, insight_enabled)"
        " VALUES (:id, :n, :u, :s, false, :d, :p, 'assistant', false)",
        id=assistant_id,
        n=name or f"assistant-{assistant_id.hex[:8]}",
        u=owner_id,
        s=str(space_id),
        d=is_default,
        p=published,
    )
    return assistant_id


async def insert_widget(
    tenant_id: UUID,
    space_id: UUID | str,
    assistant_id: UUID | str,
    *,
    requested_by: Optional[UUID] = None,
    status: str = "draft",
) -> UUID:
    widget_id = uuid4()
    await execute(
        "INSERT INTO widgets (id, public_id, tenant_id, space_id, target_type,"
        " target_id, name, status, activation_requested_at,"
        " activation_requested_by_user_id)"
        " VALUES (:id, :p, :t, :s, 'assistant', :a, 'Webbchatt', :st,"
        " CASE WHEN CAST(:r AS uuid) IS NULL THEN NULL ELSE now() END, :r)",
        id=widget_id,
        p=generate_public_id(),
        t=tenant_id,
        s=str(space_id),
        a=str(assistant_id),
        st=status,
        r=requested_by,
    )
    return widget_id


async def insert_question(
    tenant_id: UUID,
    assistant_id: UUID | str,
    *,
    user_id: Optional[UUID] = None,
    widget_id: Optional[UUID] = None,
    created_at: Optional[datetime] = None,
    question: str = "question",
    answer: str = "answer",
    session_name: str = "session",
    feedback_text: Optional[str] = None,
) -> tuple[UUID, UUID]:
    """One question in a session of a signed-in user (``user_id``) or of an
    anonymous widget visitor (``widget_id``); returns (session id,
    question id)."""
    session_id, question_id = uuid4(), uuid4()
    at = created_at or datetime.now(timezone.utc)
    await execute(
        "INSERT INTO sessions (id, name, user_id, widget_id, visitor_id,"
        " assistant_id, feedback_text, created_at, updated_at)"
        " VALUES (:id, :n, :u, :w, :v, :a, :f, :c, :c)",
        id=session_id,
        n=session_name,
        u=user_id,
        w=widget_id,
        v=uuid4() if widget_id is not None else None,
        a=str(assistant_id),
        f=feedback_text,
        c=at,
    )
    await execute(
        "INSERT INTO questions (id, tenant_id, session_id, assistant_id, question,"
        " answer, num_tokens_question, num_tokens_answer, created_at, updated_at)"
        " VALUES (:id, :t, :s, :a, :q, :ans, 1, 1, :c, :c)",
        id=question_id,
        t=tenant_id,
        s=session_id,
        a=str(assistant_id),
        q=question,
        ans=answer,
        c=at,
    )
    return session_id, question_id


def days_ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# --- HTTP ---------------------------------------------------------------------


async def create_space(
    client: AsyncClient, token: str, name: Optional[str] = None
) -> str:
    """A shared space through the product: its creator becomes its admin."""
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": name or f"oversight-{uuid4().hex[:8]}"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def create_assistant(client: AsyncClient, token: str, space_id: str) -> str:
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Kommunassistenten"},
        headers=auth(token),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def publish(
    client: AsyncClient, token: str, assistant_id: str, published: bool = True
) -> None:
    resp = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/",
        params={"published": str(published).lower()},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text


async def create_widget(
    client: AsyncClient,
    token: str,
    space_id: str,
    assistant_id: str,
    *,
    origins: tuple[str, ...] = (ORIGIN,),
) -> dict[str, Any]:
    """A draft widget; with ``origins`` its configuration blocks nothing."""
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    widget = resp.json()
    if origins:
        resp = await client.patch(
            f"/api/v1/widgets/{widget['id']}/",
            json={"revision": widget["revision"], "allowed_origins": list(origins)},
            headers=auth(token),
        )
        assert resp.status_code == 200, resp.text
        widget = resp.json()
    return widget


async def create_service_key(
    client: AsyncClient,
    token: str,
    *,
    scope_type: str = "tenant",
    scope_id: Optional[str] = None,
    permission: str = "admin",
) -> str:
    body: dict[str, Any] = {
        "name": f"svc-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
        "ownership": "service",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    resp = await client.post("/api/v1/api-keys", json=body, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


async def create_user_key(
    client: AsyncClient,
    token: str,
    *,
    scope_type: str,
    scope_id: Optional[str] = None,
    permission: str = "read",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    resp = await client.post("/api/v1/api-keys", json=body, headers=auth(token))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"secret": data["secret"], "id": data["api_key"]["id"]}


async def key_state(key_id: str) -> str:
    return await scalar("SELECT state FROM api_keys_v2 WHERE id = :id", id=key_id)


def error_code(resp: Any) -> Optional[int]:
    body = resp.json()
    return body.get("eneo_error_code")


async def set_instructions(
    tenant_id: UUID, owner_id: UUID, assistant_id: UUID | str, text: str
) -> None:
    """Make ``text`` the assistant's selected prompt."""
    prompt_id = uuid4()
    await execute(
        "UPDATE prompts_assistants SET is_selected = false WHERE assistant_id = :a",
        a=str(assistant_id),
    )
    await execute(
        "INSERT INTO prompts (id, text, user_id, tenant_id) VALUES (:id, :x, :u, :t)",
        id=prompt_id,
        x=text,
        u=owner_id,
        t=tenant_id,
    )
    await execute(
        "INSERT INTO prompts_assistants (prompt_id, assistant_id, is_selected)"
        " VALUES (:p, :a, true)",
        p=prompt_id,
        a=str(assistant_id),
    )
