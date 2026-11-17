"""The insights figures over a mix of sources: a period's summary, activity
per local day, the ratings inbox, the tenant's target list, knowledge use,
the commonest questions, tool use and the findings.

The seed is ``seed_sources``, or ``seed_quality`` for knowledge and tool calls
(see the conftest). The period is 2026-09-06 and 2026-09-07 UTC; times below
are UTC unless said otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa

from eneo.analysis.insight_findings import FINDING_THRESHOLDS, FindingThreshold
from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import KnowledgeUse
from eneo.database.tables.assistant_table import Assistants, AssistantsGroups
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import Questions

_PERIOD = {"start_time": "2026-09-06T00:00:00Z", "end_time": "2026-09-08T00:00:00Z"}


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _sources(total: int, user: int, api_key: int, widget: int) -> dict[str, int]:
    return {"total": total, "user": user, "api_key": api_key, "widget": widget}


async def _seeded(db_container, admin_user, seed_sources):
    async with db_container() as container:
        seed = await seed_sources(container, admin_user)
        token = container.auth_service().create_access_token_for_user(admin_user)
    return seed, {"Authorization": f"Bearer {token}"}


async def test_summary_counts_a_period_and_the_one_before(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    seed, headers = await _seeded(db_container, admin_user, seed_sources)
    url = "/api/v1/analysis/conversation-insights/summary/"
    params = {"assistant_id": str(seed["bygg"]), **_PERIOD}

    response = await client.get(
        url,
        params={**params, "timezone": "Europe/Stockholm", "compare": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    period = body["period"]
    assert period["conversations"] == _sources(8, 5, 1, 2)
    assert period["questions"] == _sources(12, 8, 2, 2)
    assert period["followups"] == 4
    # The visitors and the API key are no users.
    assert period["users"] == 1
    # s2, s3, s4 and both widget conversations ended after one answer.
    assert period["single_question_conversations"] == 5
    assert period["returning_users"] == 1
    # s4 and widget_1 say they cannot answer.
    assert period["unanswered"] == 2
    assert period["knowledge"] is None
    assert period["answer_ratings"] == {
        "positive": 1,
        "negative": 2,
        "with_comment": 1,
        "negative_with_comment": 1,
    }
    assert period["conversation_ratings"] == {
        "positive": 2,
        "negative": 1,
        "with_comment": 1,
        "negative_with_comment": 1,
    }

    previous = body["previous"]
    assert datetime.fromisoformat(previous["start"]) == utc(2026, 9, 4)
    assert datetime.fromisoformat(previous["end"]) == utc(2026, 9, 6)
    assert previous["conversations"] == _sources(1, 0, 0, 1)
    assert previous["questions"] == _sources(1, 0, 0, 1)

    widgets = (
        await client.get(url, params={**params, "source": "widget"}, headers=headers)
    ).json()
    assert widgets["previous"] is None
    assert widgets["period"]["conversations"] == _sources(2, 0, 0, 2)
    assert widgets["period"]["users"] == widgets["period"]["returning_users"] == 0
    assert widgets["period"]["unanswered"] == 1
    assert widgets["period"]["conversation_ratings"] == {
        "positive": 1,
        "negative": 1,
        "with_comment": 1,
        "negative_with_comment": 1,
    }

    # Returning means more than one local day: on 2026-09-07 UTC the user's
    # last question is already the 8th in Stockholm.
    one_day = {**params, "start_time": "2026-09-07T00:00:00Z"}
    stockholm = (
        await client.get(
            url, params={**one_day, "timezone": "Europe/Stockholm"}, headers=headers
        )
    ).json()
    in_utc = (await client.get(url, params=one_day, headers=headers)).json()
    assert stockholm["period"]["returning_users"] == 1
    assert in_utc["period"]["returning_users"] == 0

    insights_off = await client.get(
        url, params={**_PERIOD, "assistant_id": str(seed["other"])}, headers=headers
    )
    assert insights_off.status_code == 403, insights_off.text
    no_target = await client.get(url, params=_PERIOD, headers=headers)
    assert no_target.status_code == 400, no_target.text
    bad_zone = await client.get(
        url, params={**params, "timezone": "Mars/Olympus"}, headers=headers
    )
    assert bad_zone.status_code == 400
    assert bad_zone.json()["code"] == "invalid_timezone"


async def test_knowledge_use_follows_each_answers_mode(
    db_container, admin_user, seed_sources
):
    """Tool mode: only an answer that searched counts, and it missed when the
    search found nothing, nothing was cited or the best score is weak. Inject
    mode: every answer of the assistant searched."""
    async with db_container() as container:
        seed = await seed_sources(container, admin_user)
        session = container.session()
        collection = uuid4()
        await session.execute(
            sa.insert(CollectionsTable).values(
                id=collection,
                name="Bygglov",
                size=0,
                user_id=admin_user.id,
                tenant_id=seed["tenant_id"],
            )
        )
        await session.execute(
            sa.insert(AssistantsGroups).values(
                assistant_id=seed["bygg"], group_id=collection
            )
        )
        blob = f"eneo://info-blob/{uuid4()}"

        def search(server: str, result: str) -> list[dict[str, str]]:
            return [
                {
                    "server_name": server,
                    "tool_name": "search_knowledge",
                    "result": result,
                }
            ]

        for question_id, calls in (
            (seed["s1_q1"], search("knowledge", "1 result(s) for 'bygglov':")),
            (seed["s1_q2"], search("knowledge", "No results for 'avgift' here.")),
            # Another server's search is no knowledge search.
            (seed["widget_1_q1"], search("Webbsök", "No results for 'simhall'.")),
        ):
            await session.execute(
                sa.update(Questions)
                .where(Questions.id == question_id)
                .values(tool_calls=calls)
            )
        await session.execute(
            sa.insert(McpToolReference),
            [
                dict(
                    question_id=seed["s1_q1"],
                    uri=f"{blob}#chunk-1",
                    meta={"score": 0.62},
                    order=0,
                ),
                dict(
                    question_id=seed["s3_q1"],
                    uri=f"{blob}#chunk-2",
                    meta={"score": 0.1},
                    order=0,
                ),
            ],
        )

        repo = container.insights_repo()
        scope = InsightScope("assistant", seed["bygg"], seed["tenant_id"])
        window = InsightWindow(
            start=utc(2026, 9, 6), end=utc(2026, 9, 8), timezone="UTC"
        )

        async def knowledge(mode: str) -> KnowledgeUse | None:
            await session.execute(
                sa.update(Assistants)
                .where(Assistants.id == seed["bygg"])
                .values(knowledge_mode=mode)
            )
            figures = await repo.summarize(
                scope, window, source=None, knowledge=await repo.knowledge_setup(scope)
            )
            return figures.knowledge

        # s1_q1 hit, s1_q2 found nothing, s3_q1 cited a weak passage.
        assert await knowledge("tool") == KnowledgeUse(searched=3, missed=2)
        # All 12 answers searched; only s1_q1 had a usable hit.
        assert await knowledge("inject") == KnowledgeUse(searched=12, missed=11)


async def test_activity_counts_each_local_day_by_source(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    seed, headers = await _seeded(db_container, admin_user, seed_sources)

    response = await client.get(
        "/api/v1/analysis/conversation-insights/activity/",
        params={
            "assistant_id": str(seed["bygg"]),
            **_PERIOD,
            "timezone": "Europe/Stockholm",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    days = {day["date"]: day for day in response.json()["days"]}
    assert list(days) == ["2026-09-06", "2026-09-07", "2026-09-08"]
    assert days["2026-09-06"]["questions"] == _sources(2, 1, 0, 1)
    assert days["2026-09-07"]["questions"] == _sources(9, 6, 2, 1)
    assert days["2026-09-07"]["conversations"] == _sources(5, 3, 1, 1)
    # s2 at 22:30 UTC is past midnight in Stockholm.
    assert days["2026-09-08"]["conversations"] == _sources(1, 1, 0, 0)


async def test_feedback_inbox_pages_answer_and_conversation_ratings(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    seed, headers = await _seeded(db_container, admin_user, seed_sources)

    async def inbox(**params):
        response = await client.get(
            "/api/v1/analysis/conversation-insights/feedback/",
            params={"assistant_id": str(seed["bygg"]), **_PERIOD, **params},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = await inbox(limit=4)
    assert first["total_count"] == 6
    assert [(i["kind"], i["value"], i["question"]) for i in first["items"]] == [
        ("conversation", -1, "När öppnar simhallen?"),
        ("answer", -1, "Vad kostar det?"),
        ("answer", 1, "Hur ansöker jag om bygglov?"),
        ("answer", -1, "Status för ärende 123?"),
    ]
    vote = first["items"][0]
    # Never who gave the rating.
    assert set(vote) == {
        "kind",
        "value",
        "comment",
        "question",
        "question_id",
        "session_id",
        "source",
        "created_at",
    }
    assert (vote["comment"], vote["question_id"], vote["source"]) == (
        "Fel svar",
        None,
        "widget",
    )
    assert vote["session_id"] == str(seed["widget_1"])
    assert datetime.fromisoformat(vote["created_at"]) == utc(2026, 9, 7, 12, 0)
    answer = first["items"][1]
    assert (answer["question_id"], answer["comment"], answer["source"]) == (
        str(seed["s1_q2"]),
        "Saknar avgiften",
        "user",
    )

    second = await inbox(limit=4, cursor=first["next_cursor"])
    assert [(i["kind"], i["value"], i["question"]) for i in second["items"]] == [
        ("conversation", 1, "Var kan jag parkera?"),
        ("conversation", 1, "Öppettider?"),
    ]
    assert second["next_cursor"] is None

    commented_bad = await inbox(value=-1, has_comment=True)
    assert [i["comment"] for i in commented_bad["items"]] == [
        "Fel svar",
        "Saknar avgiften",
    ]
    widgets = await inbox(source="widget")
    assert {i["session_id"] for i in widgets["items"]} == {
        str(seed["widget_1"]),
        str(seed["widget_2"]),
    }


async def test_targets_list_usage_by_source_and_ratings_where_insights_are_on(
    db_container, admin_user, client, patch_auth_service_jwt, seed_sources
):
    seed, headers = await _seeded(db_container, admin_user, seed_sources)

    async def targets(**params):
        response = await client.get(
            "/api/v1/analysis/targets/", params={**_PERIOD, **params}, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    listed = await targets(compare=True)
    items = {item["id"]: item for item in listed["items"]}
    bygg = items[str(seed["bygg"])]
    assert listed["items"][0]["id"] == str(seed["bygg"])
    assert (bygg["kind"], bygg["insight_enabled"], bygg["personal_space"]) == (
        "assistant",
        True,
        False,
    )
    # Hidden sessions (the helper run and the analysis) stay out.
    assert bygg["conversations"] == _sources(8, 5, 1, 2)
    assert bygg["questions"] == 12
    assert bygg["previous"] == {"conversations": _sources(1, 0, 0, 1), "questions": 1}
    assert bygg["ratings"] == {"positive": 1, "negative": 2}
    # Every matching target together, not only the page.
    assert listed["totals"] == {
        "conversations": _sources(10, 7, 1, 2),
        "questions": 14,
        "previous": {"conversations": _sources(1, 0, 0, 1), "questions": 1},
    }

    other = items[str(seed["other"])]
    # Insights off: usage only.
    assert other["ratings"] is None
    assert (other["conversations"]["total"], other["questions"]) == (1, 1)
    group_chat = items[str(seed["group_chat"])]
    assert group_chat["kind"] == "group_chat"
    assert group_chat["conversations"] == _sources(1, 1, 0, 0)
    assert str(seed["hidden_assistant"]) not in items

    found = await targets(q="gc-ins")
    assert found["total_count"] == 1
    assert found["items"][0]["id"] == str(seed["group_chat"])
    assert found["items"][0]["previous"] is None
    assert found["totals"] == {
        "conversations": _sources(1, 1, 0, 0),
        "questions": 1,
        "previous": None,
    }

    used = {str(seed[key]) for key in ("bygg", "other", "group_chat")}
    unused = await targets(activity="unused")
    assert not used & {item["id"] for item in unused["items"]}
    assert unused["total_count"] == listed["total_count"] - 3

    by_name = await targets(sort="name", order="asc", limit=200)
    order = [item["id"] for item in by_name["items"] if item["id"] in used]
    assert order == [str(seed["bygg"]), str(seed["group_chat"]), str(seed["other"])]

    beyond = await targets(offset=1000, compare=True)
    assert beyond["items"] == []
    assert beyond["total_count"] == listed["total_count"]
    assert beyond["totals"] == listed["totals"]


async def _quality(db_container, admin_user, seed_quality):
    async with db_container() as container:
        seed = await seed_quality(container, admin_user)
        token = container.auth_service().create_access_token_for_user(admin_user)
    return seed, {"Authorization": f"Bearer {token}"}


async def test_knowledge_use_counts_cited_sources_across_refreshes(
    db_container, admin_user, client, patch_auth_service_jwt, seed_quality
):
    seed, headers = await _quality(db_container, admin_user, seed_quality)

    async def knowledge(**params):
        response = await client.get(
            "/api/v1/analysis/conversation-insights/knowledge/",
            params={**_PERIOD, **params},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    used = await knowledge(assistant_id=str(seed["bygg"]))
    # s1_q1 cites the superseded version, s2_q1 the active one: both count for
    # the collection. s3_q1's passage belongs to a removed document.
    assert (used["answers"], used["citing_answers"]) == (12, 2)
    assert [(s["kind"], s["id"], s["name"], s["answers"]) for s in used["sources"]] == [
        ("collection", str(seed["bygglov"]), "Bygglov", 2)
    ]
    assert used["sources"][0]["attached"] is True
    assert [(s["id"], s["answers"]) for s in used["unused"]] == [
        (str(seed["taxor"]), 0)
    ]

    widgets = await knowledge(assistant_id=str(seed["bygg"]), source="widget")
    assert (widgets["answers"], widgets["citing_answers"], widgets["sources"]) == (
        2,
        0,
        [],
    )
    # A group chat has its members' knowledge.
    group_chat = await knowledge(group_chat_id=str(seed["group_chat"]))
    assert group_chat["sources"] == []
    assert {s["name"] for s in group_chat["unused"]} == {"Bygglov", "Taxor"}


async def test_top_questions_carry_how_their_answers_fared(
    db_container, admin_user, client, patch_auth_service_jwt, seed_quality
):
    seed, headers = await _quality(db_container, admin_user, seed_quality)

    response = await client.get(
        "/api/v1/analysis/conversation-insights/questions/top/",
        params={"assistant_id": str(seed["bygg"]), **_PERIOD, "limit": 3},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Opening questions only by default.
    assert (body["total_questions"], body["include_followups"]) == (8, False)
    bygglov, declaration, swimming = body["groups"]
    assert bygglov["occurrences"] == 2 and bygglov["conversations"] == 2
    assert bygglov["share"] == 0.25
    assert bygglov["sample_session_id"] in {str(seed["s1"]), str(seed["s2"])}
    assert bygglov["ratings"] == {"positive": 1, "negative": 0}
    assert bygglov["knowledge"] == {"searched": 2, "missed": 0}
    assert (declaration["question"], declaration["unanswered"]) == (
        "Kan ni hjälpa mig med deklarationen?",
        1,
    )
    # In tool mode an answer that never searched is no miss.
    assert declaration["knowledge"] == {"searched": 0, "missed": 0}
    assert (swimming["question"], swimming["unanswered"]) == (
        "När öppnar simhallen?",
        1,
    )

    followups = await client.get(
        "/api/v1/analysis/conversation-insights/questions/top/",
        params={
            "assistant_id": str(seed["bygg"]),
            **_PERIOD,
            "include_followups": True,
            "limit": 50,
        },
        headers=headers,
    )
    groups = {g["question"]: g for g in followups.json()["groups"]}
    assert followups.json()["total_questions"] == 12
    assert groups["Vad kostar det?"]["knowledge"] == {"searched": 1, "missed": 1}
    assert groups["Vad kostar det?"]["ratings"] == {"positive": 0, "negative": 1}


async def test_tool_use_by_capability_and_tool_with_failed_and_denied_calls(
    db_container, admin_user, client, patch_auth_service_jwt, seed_quality
):
    seed, headers = await _quality(db_container, admin_user, seed_quality)

    async def tools(**params):
        response = await client.get(
            "/api/v1/analysis/conversation-insights/tools/",
            params={"assistant_id": str(seed["bygg"]), **_PERIOD, **params},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["tools"]

    # The knowledge searches and the Skill activation are left out.
    assert await tools() == [
        {
            "kind": "tool",
            "purpose": None,
            "server_name": "Grounding",
            "tool_name": "get_chat_grounding",
            "title": "Grundning",
            "calls": 2,
            "failed": 1,
            "denied": 1,
        },
        {
            "kind": "capability",
            "purpose": "web_search",
            "server_name": None,
            "tool_name": None,
            "title": None,
            "calls": 1,
            "failed": 0,
            "denied": 0,
        },
    ]
    widgets = await tools(source="widget")
    assert [(t["tool_name"], t["calls"], t["denied"]) for t in widgets] == [
        ("get_chat_grounding", 1, 1)
    ]
    assert await tools(source="api_key") == []


async def test_findings_pass_their_thresholds_and_list_their_cases(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_quality,
    monkeypatch,
):
    """The seed is small, so some thresholds are lowered; unanswered keeps
    its own and its two cases stay below it."""
    seed, headers = await _quality(db_container, admin_user, seed_quality)
    for kind, threshold in (
        ("knowledge_missed", FindingThreshold(2, 0.25)),
        ("negative_ratings", FindingThreshold(2, 0.2)),
        ("knowledge_unused", FindingThreshold(10, 0.0)),
    ):
        monkeypatch.setitem(FINDING_THRESHOLDS, kind, threshold)
    url = "/api/v1/analysis/conversation-insights/findings/"
    params = {"assistant_id": str(seed["bygg"]), **_PERIOD}

    response = await client.get(url, params=params, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["start"]) == utc(2026, 9, 6)
    assert body["source"] is None
    findings = body["findings"]
    assert [(f["kind"], f["affected"], f["base"]) for f in findings] == [
        ("knowledge_missed", 2, 4),
        ("negative_ratings", 2, 6),
        ("knowledge_unused", 1, 2),
    ]
    missed, ratings, unused = findings
    assert [e["question"] for e in missed["examples"]] == [
        "Vad kostar det?",
        "Öppettider?",
    ]
    assert [(e["comment"], e["question_id"]) for e in ratings["examples"]] == [
        ("Fel svar", None),
        ("Saknar avgiften", str(seed["s1_q2"])),
    ]
    assert [s["name"] for s in unused["sources"]] == ["Taxor"]
    assert unused["examples"] == [] and unused["tool"] is None

    async def cases(kind: str, **extra):
        response = await client.get(
            f"{url}{kind}/", params={**params, **extra}, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = await cases("knowledge_missed", limit=1)
    assert first["total_count"] == 2 and first["next_cursor"] is not None
    assert first["items"] == [
        {
            "kind": "knowledge_missed",
            "question_id": str(seed["s1_q2"]),
            "question": "Vad kostar det?",
            "session_id": str(seed["s1"]),
            "source": "user",
            "created_at": first["items"][0]["created_at"],
            "reason": "no_results",
            "best_score": None,
            "rating": -1,
        }
    ]
    second = await cases("knowledge_missed", limit=1, cursor=first["next_cursor"])
    assert [(i["question"], i["reason"], i["best_score"]) for i in second["items"]] == [
        ("Öppettider?", "weak_score", 0.1)
    ]
    assert second["next_cursor"] is None

    unanswered = await cases("unanswered")
    assert [(i["source"], i["phrase"].lower()) for i in unanswered["items"]] == [
        ("user", "kan tyvärr inte hjälpa"),
        ("widget", "hittar tyvärr ingen"),
    ]
    rephrasing = await cases("rephrasing")
    assert [(i["session_id"], len(i["questions"])) for i in rephrasing["items"]] == [
        (str(seed["s5"]), 3)
    ]

    unknown = await client.get(f"{url}tool_failures/", params=params, headers=headers)
    assert unknown.status_code == 422
