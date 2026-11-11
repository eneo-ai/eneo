"""Insights conversations are hidden from every normal session read.

An operator's analysis chat is a regular ``sessions`` row owned by the
operator and keyed on the analysed assistant, so without the hidden-session
rule it would show up in the operator's own conversation list, among the
recent conversations and chat partners, in the Insights tab's Explore list,
in the statistics counters and in exports. The ``insight_conversations``
link row is what keeps it out; these tests pin that on the repositories and
on the HTTP surfaces an operator sees.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)
_TO = datetime.now(timezone.utc) + timedelta(days=365)


async def test_session_repo_hides_insight_conversations(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.session_repo()
        visible = {seed["s1"], seed["s2"], seed["s3"], seed["s4"], seed["s5"]}

        assert await repo.get(seed["insight_session"]) is None
        assert await repo.get(seed["s1"]) is not None
        assert await repo.get_ownership(seed["insight_session"]) is None

        metadata, total = await repo.get_metadata_by_assistant(
            assistant_id=seed["bygg"], tenant_id=seed["tenant_id"]
        )
        assert {s.id for s in metadata} == visible
        assert total == len(visible)

        tenant_sessions = await repo.get_by_tenant(tenant_id=seed["tenant_id"])
        assert seed["insight_session"] not in {s.id for s in tenant_sessions}

        recent = await repo.get_recent_for_user(
            user_id=admin_user.id,
            assistant_ids=[seed["bygg"]],
            group_chat_ids=[],
            limit=50,
        )
        assert seed["insight_session"] not in {row.id for row in recent}

        # The insights conversation's own accessor still finds it.
        own = await repo.get_for_insight_conversation(
            seed["insight_session"], seed["tenant_id"]
        )
        assert own is not None
        assert (
            await repo.get_for_insight_conversation(seed["s1"], seed["tenant_id"])
            is None
        )


async def test_analysis_and_question_repos_hide_insight_conversations(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        analysis_repo = container.analysis_repo()
        question_repo = container.question_repo()

        texts = await analysis_repo.get_assistant_question_texts_since(
            assistant_id=seed["bygg"],
            from_date=_FROM,
            to_date=_TO,
            include_followups=True,
            tenant_id=seed["tenant_id"],
        )
        assert "insight question" not in {row.question for row in texts}
        assert "Hur ansöker jag om bygglov?" in {row.question for row in texts}

        count = await analysis_repo.count_assistant_questions_since(
            assistant_id=seed["bygg"],
            from_date=_FROM,
            to_date=_TO,
            tenant_id=seed["tenant_id"],
        )
        assert count == 8

        sessions, questions = await analysis_repo.get_assistant_conversation_counts(
            assistant_id=seed["bygg"],
            from_date=_FROM,
            to_date=_TO,
            tenant_id=seed["tenant_id"],
        )
        assert (sessions, questions) == (5, 8)

        session_rows = await analysis_repo.get_session_metadata_for_tenant(
            tenant_id=seed["tenant_id"], start_date=_FROM, end_date=_TO
        )
        assert seed["insight_session"] not in {row.id for row in session_rows}

        tenant_questions = await question_repo.get_by_tenant(
            tenant_id=seed["tenant_id"], start_date=_FROM, end_date=_TO
        )
        assert "insight question" not in {q.question for q in tenant_questions}


async def test_operator_lists_and_explore_hide_insight_conversations(
    db_container, admin_user, client, patch_auth_service_jwt, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    hidden = str(seed["insight_session"])

    sidebar = await client.get(
        "/api/v1/conversations/",
        params={"assistant_id": str(seed["bygg"])},
        headers=headers,
    )
    assert sidebar.status_code == 200, sidebar.text
    sidebar_ids = {item["id"] for item in sidebar.json()["items"]}
    assert hidden not in sidebar_ids
    assert str(seed["s1"]) in sidebar_ids

    opened = await client.get(f"/api/v1/conversations/{hidden}/", headers=headers)
    assert opened.status_code == 404, opened.text

    explore = await client.get(
        "/api/v1/analysis/conversation-insights/sessions/",
        params={
            "assistant_id": str(seed["bygg"]),
            "start_date": "2026-01-01",
            "end_date": "2027-01-01",
        },
        headers=headers,
    )
    assert explore.status_code == 200, explore.text
    explore_ids = {item["id"] for item in explore.json()["items"]}
    assert hidden not in explore_ids
    assert str(seed["s1"]) in explore_ids
