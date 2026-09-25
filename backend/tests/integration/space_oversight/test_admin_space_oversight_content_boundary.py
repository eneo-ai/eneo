"""The content canary: oversight shows configuration, never content.

Every column oversight must not return gets a ``SECRET-`` marker: document
titles and text, questions and answers, conversation names and feedback, app
run input and output, file names, website credentials, MCP
settings, integration paths and tokens, OneDrive names, the names of
SharePoint files and folders, prompt history and free-text internals. No marker may appear in any byte of the list, the
detail, a member change or the widget review, for an admin session or an
admin API key. The selected instructions do appear: the canary would pass
vacuously if nothing were read.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.integration.space_oversight.support import (
    add_member,
    admin_row,
    create_assistant,
    create_service_key,
    create_space,
    create_widget,
    execute,
    hub_id,
    insert_question,
    insert_user,
    key,
    publish,
    scalar,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MARKER = "SECRET-"
INSTRUCTIONS = "Visible instructions: answer politely about opening hours."
APP_INSTRUCTIONS = "Visible app instructions: summarise the meeting."


# Only a whole site keeps its name; the rest say what they are, not which.
INTEGRATIONS: list[tuple[str, str | None, str | None, str | None]] = [
    ("integration", "Socialtjänsten", "sharepoint", "site"),
    ("integration", None, "onedrive", "folder"),
    ("integration", None, "sharepoint", "file"),
    ("integration", None, "sharepoint", "folder"),
    ("integration", None, "sharepoint", None),
]


def _described(
    source: dict[str, Any],
) -> tuple[str, str | None, str | None, str | None]:
    return (
        source["kind"],
        source["name"],
        source.get("integration_type"),
        source.get("integration_item"),
    )


async def _insert(table: str, **values: Any) -> None:
    columns = ", ".join(values)
    params = ", ".join(
        f"CAST(:{name} AS jsonb)" if isinstance(value, dict) else f":{name}"
        for name, value in values.items()
    )
    await execute(
        f"INSERT INTO {table} ({columns}) VALUES ({params})",
        **{
            name: json.dumps(value) if isinstance(value, dict) else value
            for name, value in values.items()
        },
    )


async def _blob(tenant_id: UUID, owner: UUID, label: str, **source: UUID) -> None:
    await _insert(
        "info_blobs",
        id=uuid4(),
        title=f"{MARKER}{label}-title",
        text=f"{MARKER}{label}-text",
        url=f"https://intranet.example.com/{MARKER}{label}-url",
        size=10,
        source_id=uuid4(),
        version_state="active",
        user_id=owner,
        tenant_id=tenant_id,
        **source,
    )


async def _seed_content(
    tenant_id: UUID, owner: UUID, space_id: str, assistant_id: str
) -> None:
    embedding_model = await scalar(
        "SELECT id FROM embedding_models WHERE tenant_id = :t LIMIT 1", t=tenant_id
    )
    completion_model = await scalar(
        "SELECT id FROM completion_models WHERE tenant_id = :t LIMIT 1", t=tenant_id
    )

    # Instructions: the selected prompt is shown, its history never.
    await execute(
        "UPDATE prompts_assistants SET is_selected = false WHERE assistant_id = :a",
        a=assistant_id,
    )
    for text, selected in ((f"{MARKER}old-prompt", False), (INSTRUCTIONS, True)):
        prompt = uuid4()
        await _insert(
            "prompts", id=prompt, text=text, user_id=owner, tenant_id=tenant_id
        )
        await _insert(
            "prompts_assistants",
            prompt_id=prompt,
            assistant_id=UUID(assistant_id),
            is_selected=selected,
        )
    await execute(
        "UPDATE assistants SET metadata_json = CAST(:m AS jsonb),"
        " completion_model_kwargs = CAST(:k AS jsonb) WHERE id = :a",
        m=json.dumps({"note": f"{MARKER}assistant-metadata"}),
        k=json.dumps({"user": f"{MARKER}model-kwargs"}),
        a=assistant_id,
    )

    # Knowledge the assistant uses, each with a document: a collection, a
    # website that needs a login, a whole SharePoint site; and, nameless, a
    # OneDrive folder, a SharePoint file and folder (their names are
    # document titles) and a drive item not yet synced.
    collection = uuid4()
    await _insert(
        "groups",
        id=collection,
        name="Blanketter",
        tenant_id=tenant_id,
        user_id=owner,
        space_id=UUID(space_id),
        size=10,
        embedding_model_id=embedding_model,
    )
    await _blob(tenant_id, owner, "collection", group_id=collection)
    # The organisation's own collection: inherited, so counted, not listed.
    await _insert(
        "groups",
        id=uuid4(),
        name="Organisationens riktlinjer",
        tenant_id=tenant_id,
        user_id=owner,
        space_id=await hub_id(tenant_id),
        size=10,
        embedding_model_id=embedding_model,
    )
    website = uuid4()
    await _insert(
        "websites",
        id=website,
        name="Intranätet",
        url="https://intranet.example.com",
        download_files=False,
        user_id=owner,
        crawl_type="CRAWL",
        embedding_model_id=embedding_model,
        update_interval="never",
        tenant_id=tenant_id,
        space_id=UUID(space_id),
        size=10,
        http_auth_username=f"{MARKER}website-user",
        encrypted_auth_password=f"{MARKER}website-password",
        http_auth_domain=f"{MARKER}website-domain",
    )
    await _blob(tenant_id, owner, "website", website_id=website)
    integration = uuid4()
    await _insert(
        "integrations",
        id=integration,
        name="SharePoint",
        description="SharePoint",
        integration_type="sharepoint",
    )
    tenant_integration = uuid4()
    await _insert(
        "tenant_integrations",
        id=tenant_integration,
        tenant_id=tenant_id,
        integration_id=integration,
    )
    user_integration = uuid4()
    await _insert(
        "user_integrations",
        id=user_integration,
        user_id=owner,
        tenant_id=tenant_id,
        tenant_integration_id=tenant_integration,
    )
    sources = []
    for name, resource_type, item_type, drive_item in (
        ("Socialtjänsten", "site", "site_root", False),
        (f"{MARKER}onedrive-name", "onedrive", "folder", True),
        (f"{MARKER}Utredning LSS 19800101.docx", "site", "file", True),
        (f"{MARKER}sharepoint-folder-name", "site", "folder", True),
        (f"{MARKER}unsynced-item-name", "site", None, True),
    ):
        source = uuid4()
        sources.append(source)
        await _insert(
            "integration_knowledge",
            id=source,
            name=name,
            url=f"https://tenant.sharepoint.com/{MARKER}integration-url",
            space_id=UUID(space_id),
            embedding_model_id=embedding_model,
            tenant_id=tenant_id,
            user_integration_id=user_integration,
            size=10,
            site_id=f"{MARKER}site-id",
            delta_token=f"{MARKER}delta-token",
            folder_id=f"{MARKER}folder-id" if drive_item else None,
            folder_path=f"/{MARKER}folder-path",
            drive_id=f"{MARKER}drive-id",
            original_name=f"{MARKER}original-name",
            wrapper_name=f"{MARKER}wrapper-name",
            selected_item_type=item_type,
            resource_type=resource_type,
            last_sync_summary={"files": [f"{MARKER}synced-file.docx"]},
        )
        await _blob(tenant_id, owner, resource_type, integration_knowledge_id=source)
    await _insert(
        "assistants_groups", group_id=collection, assistant_id=UUID(assistant_id)
    )
    await _insert(
        "assistants_websites", website_id=website, assistant_id=UUID(assistant_id)
    )
    for source in sources:
        await _insert(
            "assistant_integration_knowledge",
            integration_knowledge_id=source,
            assistant_id=UUID(assistant_id),
        )

    # An attachment: shown as a count, never by name. (Its text columns
    # are frozen for writes; object content holds the bytes.)
    attachment = uuid4()
    await _insert(
        "files",
        id=attachment,
        name=f"{MARKER}attachment-name.pdf",
        tenant_id=tenant_id,
        user_id=owner,
    )
    await _insert(
        "assistants_files", assistant_id=UUID(assistant_id), file_id=attachment
    )

    # Tools: the server's name is configuration, its settings are secrets.
    mcp_server = uuid4()
    await _insert(
        "mcp_servers",
        id=mcp_server,
        tenant_id=tenant_id,
        name="Kalender",
        description=f"{MARKER}mcp-description",
        http_url="https://mcp.example.com",
        env_vars={"TOKEN": f"{MARKER}mcp-env-var"},
        http_auth_config_schema={"secret": f"{MARKER}mcp-auth-schema"},
    )
    await _insert(
        "spaces_mcp_servers", space_id=UUID(space_id), mcp_server_id=mcp_server
    )
    await _insert(
        "assistant_mcp_servers",
        assistant_id=UUID(assistant_id),
        mcp_server_id=mcp_server,
    )

    # Conversations: five people, so the question count is not withheld and
    # is computed from these rows.
    for index in range(5):
        user = await insert_user(tenant_id)
        await insert_question(
            tenant_id,
            assistant_id,
            user_id=user,
            question=f"{MARKER}question-{index}",
            answer=f"{MARKER}answer-{index}",
            session_name=f"{MARKER}session-{index}",
            feedback_text=f"{MARKER}feedback-{index}",
        )
    await execute(
        "UPDATE questions SET reasoning = :r, tool_calls = CAST(:t AS jsonb)"
        " WHERE assistant_id = :a",
        r=f"{MARKER}reasoning",
        t=json.dumps([{"arguments": f"{MARKER}tool-call"}]),
        a=assistant_id,
    )

    # An app with instructions and a run.
    app = uuid4()
    await _insert(
        "apps",
        id=app,
        name="Protokollhjälpen",
        tenant_id=tenant_id,
        user_id=owner,
        space_id=UUID(space_id),
        published=True,
        completion_model_id=completion_model,
    )
    for text, selected in (
        (f"{MARKER}old-app-prompt", False),
        (APP_INSTRUCTIONS, True),
    ):
        prompt = uuid4()
        await _insert(
            "prompts", id=prompt, text=text, user_id=owner, tenant_id=tenant_id
        )
        await _insert(
            "apps_prompts", prompt_id=prompt, app_id=app, is_selected=selected
        )
    await _insert(
        "app_runs",
        tenant_id=tenant_id,
        user_id=owner,
        app_id=app,
        completion_model_id=completion_model,
        input_text=f"{MARKER}app-run-input",
        output_text=f"{MARKER}app-run-output",
    )

    # A group chat whose per-assistant description is free text.
    group_chat = uuid4()
    await _insert(
        "group_chats",
        id=group_chat,
        name="Samråd",
        user_id=owner,
        space_id=UUID(space_id),
        allow_mentions=False,
        show_response_label=False,
        published=False,
        insight_enabled=False,
        type="group-chat",
        metadata_json={"note": f"{MARKER}group-chat-metadata"},
    )
    await _insert(
        "group_chats_assistants_mapping",
        group_chat_id=group_chat,
        assistant_id=UUID(assistant_id),
        user_description=f"{MARKER}group-chat-description",
    )


async def test_oversight_never_returns_content(client, admin, overseer, make_person):
    owner, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    assistant_id = await create_assistant(client, admin.token, space_id)
    await publish(client, admin.token, assistant_id)
    widget = await create_widget(client, admin.token, space_id, assistant_id)
    await _seed_content(tenant_id, owner, space_id, assistant_id)
    newcomer = await make_person([], label="newcomer")
    await add_member(space_id, await insert_user(tenant_id), "viewer")
    admin_key = key(await create_service_key(client, admin.token))

    reads = (
        "/api/v1/admin/spaces/",
        f"/api/v1/admin/spaces/{space_id}/",
        f"/api/v1/admin/widgets/{widget['id']}/",
    )
    bodies: dict[str, str] = {}
    for caller, headers in (("session", overseer.headers), ("api key", admin_key)):
        for path in reads:
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200, (caller, path, resp.text)
            bodies[f"{caller} GET {path}"] = resp.text
    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/members/",
        json={"user_id": str(newcomer.id), "role": "viewer"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text
    bodies["session POST members"] = resp.text

    leaks = {
        name: body.count(MARKER) for name, body in bodies.items() if MARKER in body
    }
    assert leaks == {}, leaks

    # Positive controls: the reads did reach the seeded configuration.
    detail = json.loads(bodies[f"session GET /api/v1/admin/spaces/{space_id}/"])
    (assistant,) = [a for a in detail["assistants"] if a["id"] == assistant_id]
    assert assistant["instructions"] == INSTRUCTIONS
    assert assistant["attachment_count"] == 1
    assert [s["name"] for s in assistant["mcp_servers"]] == ["Kalender"]
    assert Counter(_described(ref) for ref in assistant["knowledge"]) == Counter(
        [
            ("collection", "Blanketter", None, None),
            ("website", "Intranätet", None, None),
        ]
        + INTEGRATIONS
    )
    assert [app["instructions"] for app in detail["apps"]] == [APP_INSTRUCTIONS]
    knowledge = detail["knowledge"]
    (website,) = [k for k in knowledge if k["kind"] == "website"]
    assert website["requires_login"] is True
    assert Counter(
        _described(k) for k in knowledge if k["kind"] == "integration"
    ) == Counter(INTEGRATIONS)
    assert all(k["item_count"] == 1 for k in knowledge)
    assert len(knowledge) == 7
    assert detail["inherited_knowledge_count"] == 1
    assert detail["usage"]["knowledge_bytes"] == 70
    assert detail["usage"]["questions"] == 5
    assert detail["usage"]["active_users"] == 6
    # One person ran the app: that count is withheld on its own.
    assert detail["usage"]["app_runs"] is None
    assert detail["usage"]["suppressed"] is True
    assert detail["group_chats"][0]["assistant_count"] == 1

    listed = json.loads(bodies["session GET /api/v1/admin/spaces/"])
    (item,) = [item for item in listed["items"] if item["id"] == space_id]
    # The default assistant is not counted; knowledge is what the space owns.
    assert item["resources"] == {
        "assistants": 1,
        "apps": 1,
        "group_chats": 1,
        "knowledge_sources": 7,
    }
    assert item["widgets"] == {
        "active": 0,
        "paused": 0,
        "draft": 1,
        "awaiting_activation": 0,
    }
    assert item["last_activity"] == "past_week"

    review = json.loads(bodies[f"session GET /api/v1/admin/widgets/{widget['id']}/"])
    assert review["target"]["assistant"]["instructions"] == INSTRUCTIONS
    assert Counter(
        _described(k)
        for k in review["target"]["knowledge"]
        if k["kind"] == "integration"
    ) == Counter(INTEGRATIONS)
    assert (
        bodies[f"api key GET /api/v1/admin/spaces/{space_id}/"].count(INSTRUCTIONS) == 1
    )
