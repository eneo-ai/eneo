"""Integration tests for the anonymous widget surface: config, challenge, tokens."""

from __future__ import annotations

from uuid import uuid4

import altcha
import pytest

from eneo.main.config import get_settings


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("test@example.com")
        return container.auth_service().create_access_token_for_user(user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def active_widget(client, admin_token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"public-widget-{uuid4().hex[:8]}"},
        headers=_auth(admin_token),
    )
    space_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Kommunassistenten"},
        headers=_auth(admin_token),
    )
    assistant_id = resp.json()["id"]
    await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/",
        params={"published": "true"},
        headers=_auth(admin_token),
    )
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget = resp.json()
    await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "allowed_origins": ["https://www.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _solve(challenge: dict) -> str:
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    return altcha.Payload(challenge=parsed, solution=solution).to_base64()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_public_config_only_for_active_widgets(
    client, admin_token, active_widget
):
    public_id = active_widget["public_id"]

    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["public_id"] == public_id
    assert body["texts"]["subtitle"]
    assert "allowed_origins" not in body
    assert body["frame_ancestors"] == ["https://www.kommun.se"]
    assert body["single_turn"] is False
    assert resp.headers["cache-control"] == "public, max-age=60"
    etag = resp.headers["etag"]

    resp = await client.get(
        f"/api/v1/widgets/{public_id}/config/", headers={"If-None-Match": etag}
    )
    assert resp.status_code == 304

    resp = await client.get(f"/api/v1/widgets/wgt_{'x' * 22}/config/")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "widget_not_active"
    resp = await client.get("/api/v1/widgets/not-an-id/config/")
    assert resp.status_code == 404

    await client.post(
        f"/api/v1/widgets/{active_widget['id']}/pause/", headers=_auth(admin_token)
    )
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preview_token_admits_draft_widgets(client, admin_token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"preview-widget-{uuid4().hex[:8]}"},
        headers=_auth(admin_token),
    )
    space_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Utkastassistenten"},
        headers=_auth(admin_token),
    )
    assistant_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Utkast"},
        headers=_auth(admin_token),
    )
    widget = resp.json()
    public_id = widget["public_id"]

    # Still a draft: the public surface denies it outright.
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/preview-token/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["public_id"] == public_id
    assert preview["expires_in"] > 900

    resp = await client.get(
        f"/api/v1/widgets/{public_id}/config/", headers=_auth(preview["token"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_id"] == public_id
    # A draft's configuration must never be stored by a shared cache.
    assert resp.headers["cache-control"] == "private, no-store"

    # Preview tokens are minted for one sitting and never rotate: a leaked
    # one cannot renew itself.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"previous_token": preview["token"]},
        headers=_auth(preview["token"]),
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "visitor_token_invalid"

    # An ordinary (non-preview) token never admits a draft.
    resp = await client.get(
        f"/api/v1/widgets/{public_id}/config/", headers=_auth("not-a-token")
    )
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/archive/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200
    resp = await client.get(
        f"/api/v1/widgets/{public_id}/config/", headers=_auth(preview["token"])
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/preview-token/", headers=_auth(admin_token)
    )
    assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_visitor_session_lifecycle(client, admin_token, active_widget):
    public_id = active_widget["public_id"]

    resp = await client.post(f"/api/v1/widgets/{public_id}/visitor-sessions/", json={})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "challenge_required"

    resp = await client.get(f"/api/v1/widgets/{public_id}/challenge/")
    assert resp.status_code == 200, resp.text
    challenge = resp.json()
    assert challenge["parameters"]["algorithm"] == "SHA-256"
    payload = _solve(challenge)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/", json={"altcha": payload}
    )
    assert resp.status_code == 200, resp.text
    session = resp.json()
    assert session["expires_in"] == get_settings().widget_visitor_token_ttl_seconds
    token, visitor_id = session["token"], session["visitor_id"]

    # The same solution cannot mint twice.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/", json={"altcha": payload}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "challenge_replayed"

    # Silent rotation keeps the visitor id without a new challenge.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"previous_token": token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visitor_id"] == visitor_id
    rotated = resp.json()["token"]

    # A configuration change bumps the generation: old tokens are stale.
    resp = await client.patch(
        f"/api/v1/widgets/{active_widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{active_widget['id']}/",
                    headers=_auth(admin_token),
                )
            ).json()["revision"],
            "limits": {"messages_per_visitor_10min": 5},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"previous_token": rotated},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "visitor_token_stale"

    # A garbage token is invalid, not stale.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"previous_token": "abc.def.ghi"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "visitor_token_invalid"

    # Pausing hides the widget entirely from the public surface.
    await client.post(
        f"/api/v1/widgets/{active_widget['id']}/pause/", headers=_auth(admin_token)
    )
    resp = await client.get(f"/api/v1/widgets/{public_id}/challenge/")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bot_protection_none_requires_policy(client, admin_token, active_widget):
    public_id = active_widget["public_id"]

    resp = await client.patch(
        f"/api/v1/widgets/{active_widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{active_widget['id']}/",
                    headers=_auth(admin_token),
                )
            ).json()["revision"],
            "bot_protection": "none",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert "bot_protection_none_not_allowed" in resp.text

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"allow_bot_protection_none": True},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"/api/v1/widgets/{active_widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{active_widget['id']}/",
                    headers=_auth(admin_token),
                )
            ).json()["revision"],
            "bot_protection": "none",
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    issued = (
        await client.post(f"/api/v1/widgets/{public_id}/visitor-sessions/", json={})
    ).json()
    known_visitor, visitor_key = issued["visitor_id"], issued["visitor_key"]

    # The pseudonym survives a fresh mint only together with its key.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"visitor_id": known_visitor, "visitor_key": visitor_key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visitor_id"] == known_visitor
    assert resp.json()["visitor_key"] == visitor_key

    # A claimed id without the right key starts a new pseudonym instead.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"visitor_id": known_visitor, "visitor_key": "00" * 32},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visitor_id"] != known_visitor
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"visitor_id": str(uuid4())},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visitor_id"] != known_visitor


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unpublished_assistant_takes_its_widget_offline(
    client, admin_token, active_widget
):
    public_id = active_widget["public_id"]
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=60"

    resp = await client.post(
        f"/api/v1/assistants/{active_widget['target_id']}/publish/",
        params={"published": "false"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    # Same answer as a pause: the embed page shows its unavailable state
    # instead of a permission error from the ask pipeline.
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "widget_not_active"

    resp = await client.get("/api/v1/admin/widgets/", headers=_auth(admin_token))
    item = next(i for i in resp.json()["items"] if i["public_id"] == public_id)
    assert item["status"] == "active"
    assert item["activation_blockers"] == ["target_not_published"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forbidding_bot_protection_none_holds_widgets_already_on_it(
    client, admin_token, active_widget
):
    public_id = active_widget["public_id"]
    widget_url = f"/api/v1/widgets/{active_widget['id']}/"
    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"allow_bot_protection_none": True},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    revision = (await client.get(widget_url, headers=_auth(admin_token))).json()[
        "revision"
    ]
    resp = await client.patch(
        widget_url,
        json={"revision": revision, "bot_protection": "none"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/widgets/{public_id}/visitor-sessions/", json={})
    assert resp.status_code == 200, resp.text
    issued = resp.json()
    config = (await client.get(f"/api/v1/widgets/{public_id}/config/")).json()
    assert config["bot_protection"] == "none"

    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"allow_bot_protection_none": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    # The widget keeps its setting; the visitor surface holds it to the policy.
    stored = (await client.get(widget_url, headers=_auth(admin_token))).json()
    assert stored["bot_protection"] == "none"
    assert "bot_protection_none_not_allowed" in stored["activation_blockers"]
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["bot_protection"] == "altcha"
    assert resp.json()["token_generation"] > config["token_generation"]

    resp = await client.post(f"/api/v1/widgets/{public_id}/visitor-sessions/", json={})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "challenge_required"
    # A token minted without a challenge cannot renew itself past the change.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"previous_token": issued["token"]},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "visitor_token_stale"

    challenge = (await client.get(f"/api/v1/widgets/{public_id}/challenge/")).json()
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/",
        json={"altcha": _solve(challenge)},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_policy_change_reaches_a_cached_config(
    client, admin_token, active_widget
):
    public_id = active_widget["public_id"]
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.json()["single_turn"] is False
    etag = resp.headers["etag"]

    # Only the policy changes; the widget row keeps its 30 days.
    resp = await client.patch(
        "/api/v1/admin/widget-policy/",
        json={"max_retention_days": 0},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        f"/api/v1/widgets/{public_id}/config/", headers={"If-None-Match": etag}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["single_turn"] is True
    assert resp.headers["etag"] != etag
