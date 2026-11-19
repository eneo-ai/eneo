"""An assistant's insights count its conversations from every source.

Users, service API keys and website widget visitors all talk to the same
assistant. The insights figures and lists count and list every source, each
conversation tagged with its source, while the figures for users stay what
they were, and no per-user view ever shows an API-key or widget conversation.
"""

from __future__ import annotations

_FAR = {"from_date": "2000-01-01", "to_date": "2100-01-01"}
_FAR_TIMES = {
    "start_time": "2000-01-01T00:00:00Z",
    "end_time": "2100-01-01T00:00:00Z",
}


async def _headers(container, admin_user) -> dict[str, str]:
    token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def test_assistant_figures_count_every_source_and_keep_the_user_figures(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    async with db_container() as container:
        seed = await seed_sources(container, admin_user)
        headers = await _headers(container, admin_user)
    bygg = str(seed["bygg"])

    async def stats(**params):
        response = await client.get(
            "/api/v1/analysis/conversation-insights/",
            params={"assistant_id": bygg, **_FAR_TIMES, **params},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        return (
            body["total_conversations"],
            body["total_questions"],
            body["feedback"],
        )

    assert await stats() == (9, 13, {"positive": 1, "negative": 2})
    # The figures for users are those counted before other sources were.
    assert await stats(source="user") == (5, 8, {"positive": 1, "negative": 1})
    assert await stats(source="api_key") == (1, 2, {"positive": 0, "negative": 1})
    assert await stats(source="widget") == (3, 3, {"positive": 0, "negative": 0})

    history = await client.get(
        f"/api/v1/analysis/assistants/{bygg}/questions/",
        params={**_FAR, "include_followups": True},
        headers=headers,
    )
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 13
    sources = {item["question"]: item["source"] for item in history.json()["items"]}
    assert sources["När öppnar simhallen?"] == "widget"
    assert sources["Och ärende 124?"] == "api_key"
    assert sources["Vad kostar det?"] == "user"

    widget_history = await client.get(
        f"/api/v1/analysis/assistants/{bygg}/questions/",
        params={**_FAR, "include_followups": True, "source": "widget"},
        headers=headers,
    )
    assert {item["source"] for item in widget_history.json()["items"]} == {"widget"}
    assert widget_history.json()["total_count"] == 3

    ratings = await client.get(
        f"/api/v1/analysis/assistants/{bygg}/feedback/",
        params={**_FAR, "include_followups": True, "source": "api_key"},
        headers=headers,
    )
    assert ratings.json() == {"positive": 0, "negative": 1}

    counts = await client.get("/api/v1/analysis/counts/", headers=headers)
    assert counts.status_code == 200, counts.text
    # Hidden sessions stay out; API-key and widget conversations count.
    assert (counts.json()["sessions"], counts.json()["questions"]) == (11, 15)


async def test_explore_lists_every_source_and_no_per_user_view_shows_them(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    async with db_container() as container:
        seed = await seed_sources(container, admin_user)
        headers = await _headers(container, admin_user)
    bygg = str(seed["bygg"])
    others = {str(seed[key]) for key in ("api", "widget_1", "widget_2", "widget_old")}

    explore = await client.get(
        "/api/v1/analysis/conversation-insights/sessions/",
        params={
            "assistant_id": bygg,
            "start_date": "2000-01-01",
            "end_date": "2100-01-01",
        },
        headers=headers,
    )
    assert explore.status_code == 200, explore.text
    tags = {item["id"]: item["source"] for item in explore.json()["items"]}
    assert explore.json()["total_count"] == 9
    assert tags[str(seed["s1"])] == "user"
    assert tags[str(seed["api"])] == "api_key"
    assert tags[str(seed["widget_1"])] == "widget"

    widgets = await client.get(
        "/api/v1/analysis/conversation-insights/sessions/",
        params={"assistant_id": bygg, "source": "widget"},
        headers=headers,
    )
    assert {item["id"] for item in widgets.json()["items"]} == {
        str(seed["widget_1"]),
        str(seed["widget_2"]),
        str(seed["widget_old"]),
    }

    opened = await client.get(
        f"/api/v1/analysis/conversation-insights/sessions/{seed['widget_1']}/",
        headers=headers,
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["source"] == "widget"
    assert [m["question"] for m in opened.json()["messages"]] == [
        "När öppnar simhallen?"
    ]

    own = await client.get(
        "/api/v1/conversations/", params={"assistant_id": bygg}, headers=headers
    )
    assert own.status_code == 200, own.text
    own_ids = {item["id"] for item in own.json()["items"]}
    assert str(seed["s1"]) in own_ids
    assert not own_ids & others

    activity = await client.get(
        "/api/v1/analysis/assistant-activity/",
        params={"start_date": "2000-01-01", "end_date": "2100-01-01"},
        headers=headers,
    )
    # Visitors and API keys are no users.
    assert activity.json()["active_user_count"] == 1
