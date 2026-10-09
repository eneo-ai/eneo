"""The document template library through the admin API, against a real database.

Without a tool runtime, uploads are stored unchecked; the library, the default,
the signed download the runtime uses, and an assistant's choice all work.
"""

import io
import zipfile
from typing import Any
from uuid import uuid4

import pytest

from eneo.authentication.signed_urls import build_signed_document_template_url

BASE = "/api/v1/document-templates"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx(marker: str = "mall") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<w:document>{marker}</w:document>")
    return buffer.getvalue()


@pytest.fixture
def auth(admin_user_api_key: Any) -> dict[str, str]:
    return {"X-API-Key": admin_user_api_key.key}


async def _upload(
    client, auth, name: str, *, is_default: bool = False, content: bytes | None = None
):
    return await client.post(
        f"{BASE}/",
        headers=auth,
        files={"file": (f"{name}.docx", content or _docx(name), DOCX)},
        data={"name": name, "is_default": "true" if is_default else "false"},
    )


async def test_library_upload_default_rename_and_delete(client, auth):
    created = await _upload(client, auth, "Rapportmall")
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["status"] == "unchecked"
    assert template["is_default"] is False
    assert template["filename"] == "Rapportmall.docx"
    assert template["selected_by"] == 0

    listed = (await client.get(f"{BASE}/", headers=auth)).json()
    assert [t["id"] for t in listed["items"]] == [template["id"]]
    # The test settings may name a runtime; an unreachable one leaves uploads unchecked.
    assert isinstance(listed["runtime_configured"], bool)

    # One default per tenant: making another the default clears the first.
    made_default = await client.patch(
        f"{BASE}/{template['id']}/", headers=auth, json={"is_default": True}
    )
    assert made_default.json()["is_default"] is True
    second = (await _upload(client, auth, "Brevmall", is_default=True)).json()
    assert second["is_default"] is True
    first = (await client.get(f"{BASE}/{template['id']}/", headers=auth)).json()
    assert first["is_default"] is False

    # Names are unique among live templates.
    conflict = await _upload(client, auth, "brevmall")
    assert conflict.status_code == 400
    renamed = await client.patch(
        f"{BASE}/{template['id']}/", headers=auth, json={"name": "Rapport 2026"}
    )
    assert renamed.json()["name"] == "Rapport 2026"

    content = await client.get(f"{BASE}/{template['id']}/content/", headers=auth)
    assert content.status_code == 200
    assert content.content == _docx("Rapportmall")

    deleted = await client.delete(f"{BASE}/{second['id']}/", headers=auth)
    assert deleted.status_code == 204
    remaining = (await client.get(f"{BASE}/", headers=auth)).json()["items"]
    assert [t["name"] for t in remaining] == ["Rapport 2026"]
    assert (
        await client.get(f"{BASE}/{second['id']}/", headers=auth)
    ).status_code == 404


async def test_rejects_what_is_not_a_word_template(client, auth):
    not_zip = await client.post(
        f"{BASE}/",
        headers=auth,
        files={"file": ("mall.docx", b"not a zip", DOCX)},
        data={"name": "Trasig"},
    )
    assert not_zip.status_code == 400
    macro = await client.post(
        f"{BASE}/",
        headers=auth,
        files={"file": ("mall.docm", _docx(), DOCX)},
        data={"name": "Makro"},
    )
    assert macro.status_code in (400, 415)


async def test_signed_download_serves_the_template_to_its_tenant_only(
    client, auth, admin_user
):
    template = (await _upload(client, auth, "Signerad")).json()
    url = build_signed_document_template_url(
        template["id"],
        base_url="http://test",
        expires_in=300,
        tenant_id=admin_user.tenant_id,
    )
    path = url.removeprefix("http://test")
    response = await client.get(path)
    assert response.status_code == 200
    assert response.content == _docx("Signerad")
    assert response.headers["content-type"].startswith(DOCX)

    foreign = build_signed_document_template_url(
        template["id"], base_url="http://test", expires_in=300, tenant_id=uuid4()
    )
    assert (await client.get(foreign.removeprefix("http://test"))).status_code == 404
    assert (await client.get(f"{path}x")).status_code in (401, 403)


async def test_an_assistant_selects_a_template_and_falls_back_when_it_goes(
    client, auth
):
    template = (await _upload(client, auth, "Vald")).json()
    space = await client.post("/api/v1/spaces/", headers=auth, json={"name": "Mallar"})
    assert space.status_code in (200, 201), space.text
    assistant = await client.post(
        "/api/v1/assistants/",
        headers=auth,
        json={"name": "Skrivare", "space_id": space.json()["id"]},
    )
    assert assistant.status_code in (200, 201), assistant.text
    assistant_id = assistant.json()["id"]
    assert assistant.json()["document_template"] == {
        "mode": "default",
        "template_id": None,
    }

    selected = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        headers=auth,
        json={"document_template": {"mode": "selected", "template_id": template["id"]}},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["document_template"] == {
        "mode": "selected",
        "template_id": template["id"],
    }
    listed = (await client.get(f"{BASE}/", headers=auth)).json()["items"]
    assert listed[0]["selected_by"] == 1

    unknown = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        headers=auth,
        json={"document_template": {"mode": "selected", "template_id": str(uuid4())}},
    )
    assert unknown.status_code == 400

    assert (
        await client.delete(f"{BASE}/{template['id']}/", headers=auth)
    ).status_code == 204
    after = (
        await client.get(f"/api/v1/assistants/{assistant_id}/", headers=auth)
    ).json()
    assert after["document_template"] == {"mode": "default", "template_id": None}
