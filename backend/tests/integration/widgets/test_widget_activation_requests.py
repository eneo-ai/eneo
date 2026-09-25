"""Editors request activation; tenant admins review, send back or activate.

The editor has the widgets permission and edits the space. The overseer is
a tenant admin without membership: they review the widget and settle the
request, but gain no editor access and cannot test it live.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.database import sessionmanager
from eneo.roles.permissions import Permission
from tests.integration.space_oversight.support import (
    Person,
    add_member,
    admin_row,
    audit_rows,
    create_assistant,
    create_service_key,
    create_space,
    create_widget,
    hub_id,
    insert_assistant,
    insert_tenant,
    insert_widget,
    key,
    new_person,
    publish,
    scalar,
    seeded_admin,
    set_instructions,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

INSTRUCTIONS = "Svara vänligt om öppettider och hänvisa till kontaktcenter."
SEND_BACK = "Lägg till en kontaktadress i undertexten."


@pytest.fixture
async def admin(db_container, patch_auth_service_jwt) -> Person:
    return await seeded_admin(db_container)


@pytest.fixture
async def overseer(db_container, patch_auth_service_jwt) -> Person:
    """A tenant admin without the widgets permission and without membership."""
    return await new_person(db_container, [Permission.ADMIN], label="overseer")


@pytest.fixture
async def editor(db_container, patch_auth_service_jwt) -> Person:
    return await new_person(
        db_container, [Permission.WIDGETS, Permission.ASSISTANTS], label="editor"
    )


@pytest.fixture
async def queued(monkeypatch) -> list[dict[str, Any]]:
    """Audit entries sent to the queue (ordinary, configurable actions)."""
    entries: list[dict[str, Any]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        entries.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return entries


@pytest.fixture
async def setup(client, admin: Person, editor: Person) -> dict[str, Any]:
    """A space the editor edits, with a published assistant and a draft
    widget whose configuration blocks nothing."""
    owner, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    await add_member(space_id, editor.id, "editor")
    assistant_id = await create_assistant(client, admin.token, space_id)
    await set_instructions(tenant_id, owner, assistant_id, INSTRUCTIONS)
    await publish(client, admin.token, assistant_id)
    widget = await create_widget(client, admin.token, space_id, assistant_id)
    return {"space_id": space_id, "assistant_id": assistant_id, "widget": widget}


def _path(widget: dict[str, Any], suffix: str = "") -> str:
    return f"/api/v1/widgets/{widget['id']}/{suffix}"


async def _request(client, person: Person, widget: dict[str, Any]):
    return await client.post(
        _path(widget, "activation-request/"), headers=person.headers
    )


async def _decline(
    client, person: Person, widget: dict[str, Any], reason: str = SEND_BACK
):
    return await client.post(
        _path(widget, "activation-request/decline/"),
        json={"reason": reason},
        headers=person.headers,
    )


async def _review_fields(widget_id: str) -> dict[str, Any]:
    async with sessionmanager.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    "SELECT status, activation_requested_at,"
                    " activation_requested_by_user_id, activation_declined_at,"
                    " activation_declined_by_user_id, activation_decline_reason"
                    " FROM widgets WHERE id = :id"
                ),
                {"id": widget_id},
            )
        ).one()
    return dict(row._mapping)


def _queued(entries: list[dict[str, Any]], action: ActionType) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry["action"] == action]


async def test_editor_requests_activation_once_and_can_withdraw(
    client, editor, setup, queued
):
    widget = setup["widget"]

    resp = await _request(client, editor, widget)
    assert resp.status_code == 200, resp.text
    requested = resp.json()
    assert requested["activation_requested_by_user_id"] == str(editor.id)
    assert requested["activation_requested_at"] is not None
    assert requested["status"] == "draft"

    # A second click changes nothing: same request, same revision, no entry.
    resp = await _request(client, editor, widget)
    assert resp.status_code == 200, resp.text
    again = resp.json()
    assert again["activation_requested_at"] == requested["activation_requested_at"]
    assert again["revision"] == requested["revision"]
    assert len(_queued(queued, ActionType.WIDGET_ACTIVATION_REQUESTED)) == 1

    resp = await client.delete(
        _path(widget, "activation-request/"), headers=editor.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["activation_requested_at"] is None
    resp = await client.delete(
        _path(widget, "activation-request/"), headers=editor.headers
    )
    assert resp.status_code == 200, resp.text
    assert len(_queued(queued, ActionType.WIDGET_ACTIVATION_REQUEST_WITHDRAWN)) == 1

    fields = await _review_fields(widget["id"])
    assert fields["activation_requested_at"] is None
    assert fields["activation_requested_by_user_id"] is None


async def test_a_returned_request_is_visible_to_the_editor(
    client, editor, overseer, setup
):
    widget = setup["widget"]
    requested = (await _request(client, editor, widget)).json()

    resp = await _decline(client, overseer, widget, f"  {SEND_BACK}\r\n")
    assert resp.status_code == 200, resp.text

    resp = await client.get(_path(widget), headers=editor.headers)
    assert resp.status_code == 200, resp.text
    returned = resp.json()
    assert returned["activation_requested_at"] is None
    assert returned["activation_declined_by_user_id"] == str(overseer.id)
    assert returned["activation_decline_reason"] == SEND_BACK
    assert returned["activation_declined_at"] is not None

    (entry,) = await audit_rows(action="widget_activation_request_declined")
    assert entry["actor_id"] == overseer.id
    extra = entry["metadata"]["extra"]
    assert extra["reason"] == SEND_BACK
    assert extra["actor_is_space_member"] is False
    assert extra["activation_request"] == {
        "requested_at": extra["activation_request"]["requested_at"],
        "requested_by_user_id": str(editor.id),
    }
    assert extra["activation_request"]["requested_at"] is not None
    assert SEND_BACK not in entry["description"]

    # Asking again clears what was sent back.
    resp = await _request(client, editor, widget)
    assert resp.status_code == 200, resp.text
    again = resp.json()
    assert again["activation_declined_at"] is None
    assert again["activation_decline_reason"] is None
    assert again["activation_requested_at"] != requested["activation_requested_at"]


@pytest.mark.parametrize(
    "reason",
    [
        # Nine characters once the zero-width space is gone and e + U+0301
        # composes: a 422, never an IntegrityError from the stored CHECK.
        "abcdefgh" + "e\u200b\u0301",
        "\u2060" * 10,
        "\U000e0041" * 12,
        "\u3164" * 10,
    ],
    ids=["composes-short", "word-joiners", "tag-characters", "hangul-fillers"],
)
async def test_a_reason_without_ten_visible_characters_is_refused(
    client, editor, overseer, setup, reason
):
    widget = setup["widget"]
    await _request(client, editor, widget)

    resp = await _decline(client, overseer, widget, reason)
    assert resp.status_code == 422, resp.text
    fields = await _review_fields(widget["id"])
    assert fields["activation_requested_at"] is not None
    assert fields["activation_decline_reason"] is None


async def test_requests_are_refused_like_activation(
    client, db_container, admin, editor, overseer, setup, patch_auth_service_jwt
):
    space_id, assistant_id = setup["space_id"], setup["assistant_id"]
    widget = setup["widget"]

    resp = await _decline(client, overseer, widget)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "widget_activation_request_missing"

    second_assistant = await create_assistant(client, admin.token, space_id)
    unconfigured = await create_widget(
        client, admin.token, space_id, second_assistant, origins=()
    )
    resp = await _request(client, editor, unconfigured)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "widget_serving_blocked"
    assert set(resp.json()["detail"]["blockers"]) == {
        "allowed_origins_empty",
        "target_not_published",
    }

    await publish(client, admin.token, assistant_id, published=False)
    resp = await _request(client, editor, widget)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["blockers"] == ["target_not_published"]
    await publish(client, admin.token, assistant_id)

    # Only people who edit the space with the widgets permission may ask.
    without_widgets = await new_person(
        db_container, [Permission.ASSISTANTS], label="ed"
    )
    viewer = await new_person(db_container, [Permission.WIDGETS], label="viewer")
    await add_member(space_id, without_widgets.id, "editor")
    await add_member(space_id, viewer.id, "viewer")
    for person in (without_widgets, viewer, overseer):
        resp = await _request(client, person, widget)
        assert resp.status_code == 403, resp.text

    assert (await _request(client, editor, widget)).status_code == 200
    resp = await _decline(client, editor, widget)
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        _path(widget, "activate/"), json={"revision": 0}, headers=editor.headers
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(_path(widget, "activate/"), headers=admin.headers)
    assert resp.status_code == 200, resp.text
    resp = await _request(client, editor, widget)
    assert resp.status_code == 400, resp.text
    assert (await _review_fields(widget["id"]))["activation_requested_at"] is None


async def test_non_member_admin_reviews_and_activates_the_reviewed_revision(
    client, editor, overseer, setup
):
    widget = setup["widget"]
    await _request(client, editor, widget)

    resp = await client.get(
        f"/api/v1/admin/widgets/{widget['id']}/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()
    assert review["space_kind"] == "shared"
    assert review["viewer_role"] is None
    assert review["viewer_membership"]["joinable_roles"] == [
        "viewer",
        "editor",
        "admin",
    ]
    assert review["target"]["assistant"]["id"] == setup["assistant_id"]
    assert review["target"]["assistant"]["instructions"] == INSTRUCTIONS
    assert review["activation_requested_by"] == {
        "id": str(editor.id),
        "name": editor.username,
        "email": editor.email,
    }
    assert review["widget"]["activation_blockers"] == []
    reviewed = review["widget"]["revision"]

    # Review gives no editor access and no live answers from the space.
    resp = await client.post(_path(widget, "preview-token/"), headers=overseer.headers)
    assert resp.status_code == 403, resp.text
    resp = await client.get(_path(widget), headers=overseer.headers)
    assert resp.status_code == 403, resp.text
    resp = await client.patch(
        _path(widget),
        json={"revision": reviewed, "name": "Ändrad av administratören"},
        headers=overseer.headers,
    )
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        _path(widget, "activate/"),
        json={"revision": reviewed - 1},
        headers=overseer.headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "widget_revision_conflict"
    assert (await _review_fields(widget["id"]))["status"] == "draft"

    resp = await client.post(
        _path(widget, "activate/"),
        json={"revision": reviewed},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert resp.json()["activation_requested_at"] is None
    fields = await _review_fields(widget["id"])
    assert (fields["status"], fields["activation_requested_at"]) == ("active", None)

    (entry,) = await audit_rows(action="widget_activated")
    extra = entry["metadata"]["extra"]
    assert extra["actor_is_space_member"] is False
    assert extra["reviewed_revision"] == reviewed
    assert extra["activation_request"]["requested_by_user_id"] == str(editor.id)


async def test_member_admin_tests_only_a_published_target(
    client, admin, overseer, setup
):
    widget = setup["widget"]
    await add_member(setup["space_id"], overseer.id, "viewer")

    resp = await client.post(_path(widget, "preview-token/"), headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_id"] == widget["public_id"]
    # Minted on membership that a leave or removal ends: short-lived.
    assert resp.json()["expires_in"] == 600

    await publish(client, admin.token, setup["assistant_id"], published=False)
    resp = await client.post(_path(widget, "preview-token/"), headers=overseer.headers)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == {
        "blockers": ["target_not_published"],
        "code": "widget_serving_blocked",
        "message": resp.json()["detail"]["message"],
    }


async def test_review_is_for_the_tenants_admins(
    client, db_container, admin, editor, setup, patch_auth_service_jwt
):
    widget = setup["widget"]
    review = f"/api/v1/admin/widgets/{widget['id']}/"

    resp = await client.get(review, headers=editor.headers)
    assert resp.status_code == 403, resp.text

    other_admin = await new_person(
        db_container, [Permission.ADMIN], label="other", tenant_id=await insert_tenant()
    )
    resp = await client.get(review, headers=other_admin.headers)
    assert resp.status_code == 404, resp.text
    resp = await _decline(client, other_admin, widget)
    assert resp.status_code == 404, resp.text

    tenant_admin_key = key(await create_service_key(client, admin.token))
    resp = await client.get(review, headers=tenant_admin_key)
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        _path(widget, "activation-request/"), headers=tenant_admin_key
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(
        _path(widget, "activation-request/decline/"),
        json={"reason": SEND_BACK},
        headers=tenant_admin_key,
    )
    assert resp.status_code == 403, resp.text


async def test_review_of_personal_and_organisation_widgets(client, admin, overseer):
    """Outside shared spaces the review still works: a personal assistant is
    never shown (it cannot be published), the organisation's is."""
    owner, tenant_id = await admin_row()
    resp = await client.get("/api/v1/spaces/type/personal/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    personal = resp.json()["id"]
    hub = str(await hub_id(tenant_id))
    reviews: dict[str, dict[str, Any]] = {}
    for kind, space_id in (("personal", personal), ("organization", hub)):
        assistant = await insert_assistant(space_id, owner, name=f"{kind}-assistent")
        await set_instructions(tenant_id, owner, assistant, INSTRUCTIONS)
        widget_id = await insert_widget(tenant_id, space_id, assistant)
        resp = await client.get(
            f"/api/v1/admin/widgets/{widget_id}/", headers=overseer.headers
        )
        assert resp.status_code == 200, resp.text
        reviews[kind] = resp.json()

    assert reviews["personal"]["space_kind"] == "personal"
    assert reviews["personal"]["target"] is None
    assert reviews["personal"]["viewer_role"] is None
    assert reviews["personal"]["viewer_membership"] is None
    assert reviews["organization"]["space_kind"] == "organization"
    assert (
        reviews["organization"]["target"]["assistant"]["instructions"] == INSTRUCTIONS
    )
    assert reviews["organization"]["viewer_membership"] is None


async def test_archiving_with_the_assistant_clears_the_request(
    client, admin, editor, setup
):
    widget = setup["widget"]
    await _request(client, editor, widget)

    resp = await client.delete(
        f"/api/v1/assistants/{setup['assistant_id']}/", headers=admin.headers
    )
    assert resp.status_code == 204, resp.text

    fields = await _review_fields(widget["id"])
    assert fields["status"] == "archived"
    assert fields["activation_requested_at"] is None
    assert fields["activation_requested_by_user_id"] is None


async def test_overview_lists_pending_requests_first_and_counts_them(
    client, admin, editor, setup
):
    space_id = setup["space_id"]
    widgets = {"requested": setup["widget"]}
    for name in ("active", "draft"):
        assistant = await create_assistant(client, admin.token, space_id)
        await publish(client, admin.token, assistant)
        widgets[name] = await create_widget(client, admin.token, space_id, assistant)
    resp = await client.post(
        _path(widgets["active"], "activate/"), headers=admin.headers
    )
    assert resp.status_code == 200, resp.text
    # The most recently touched widget is not the one with the request.
    await _request(client, editor, widgets["requested"])
    await client.patch(
        _path(widgets["draft"]),
        json={"revision": widgets["draft"]["revision"], "name": "Senast ändrad"},
        headers=admin.headers,
    )

    resp = await client.get("/api/v1/admin/widgets/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    overview = resp.json()
    assert [item["id"] for item in overview["items"]] == [
        widgets["requested"]["id"],
        widgets["active"]["id"],
        widgets["draft"]["id"],
    ]
    assert overview["totals"]["awaiting_activation"] == 1
    first = overview["items"][0]
    assert first["activation_requested_at"] is not None
    assert first["activation_requested_by"] == {
        "id": str(editor.id),
        "name": editor.username,
        "email": editor.email,
    }
    assert overview["items"][1]["activation_requested_by"] is None


@pytest.mark.parametrize(
    ("constraint", "assignments"),
    [
        (
            "ck_widgets_activation_request_status",
            "status = 'archived', activation_requested_at = now()",
        ),
        (
            "ck_widgets_activation_decline_pair",
            "activation_declined_at = now()",
        ),
        (
            "ck_widgets_activation_request_xor_decline",
            "activation_requested_at = now(), activation_declined_at = now(),"
            " activation_decline_reason = 'Saknar kontaktuppgifter.'",
        ),
        (
            "ck_widgets_activation_decline_reason_length",
            "activation_declined_at = now(), activation_decline_reason = 'Kort'",
        ),
    ],
)
async def test_check_constraints_backstop_the_review_fields(
    setup, constraint: str, assignments: str
):
    widget_id = UUID(setup["widget"]["id"])
    with pytest.raises(sa.exc.IntegrityError, match=constraint):
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.text(f"UPDATE widgets SET {assignments} WHERE id = :id"),
                {"id": widget_id},
            )
    assert (
        await scalar(
            "SELECT activation_requested_at IS NULL AND activation_declined_at IS NULL"
            " FROM widgets WHERE id = :id",
            id=widget_id,
        )
        is True
    )
