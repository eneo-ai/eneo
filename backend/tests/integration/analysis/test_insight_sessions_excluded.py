"""Insight conversations are hidden from every normal session path.

The operator's analysis chat is a regular ``sessions`` row owned by the
operator and keyed on the analysed assistant, so without the hidden-session
rule it would show up in the operator's own conversation sidebar, in the
Insights tab's Explore list, in the statistics counters and in exports. The
``insight_conversations`` link row is what keeps it out; these tests pin
that on the repositories and on the two HTTP surfaces an operator sees.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)
_TO = datetime.now(timezone.utc) + timedelta(days=365)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_repo_hides_insight_conversations(
    db_container, admin_user, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        repo = container.session_repo()

        assert await repo.get(seed["insight_session"]) is None
        assert await repo.get(seed["s1"]) is not None

        sessions, total = await repo.get_by_assistant(
            assistant_id=seed["bygg"], tenant_id=seed["tenant_id"]
        )
        ids = {s.id for s in sessions}
        assert seed["insight_session"] not in ids
        assert seed["helper_session"] not in ids
        assert {seed["s1"], seed["s2"], seed["s3"], seed["s4"], seed["s5"]} <= ids
        assert total == len(sessions) == 5

        metadata, _ = await repo.get_metadata_by_assistant(
            assistant_id=seed["bygg"], tenant_id=seed["tenant_id"]
        )
        assert seed["insight_session"] not in {s.id for s in metadata}


@pytest.mark.asyncio
@pytest.mark.integration
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

        tenant_questions = await question_repo.get_by_tenant(
            tenant_id=seed["tenant_id"], start_date=_FROM, end_date=_TO
        )
        assert "insight question" not in {q.question for q in tenant_questions}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_operator_sidebar_and_explore_list_hide_insight_conversations(
    db_container, admin_user, client, patch_auth_service_jwt, seed_insights
):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}

    sidebar = await client.get(
        "/api/v1/conversations/",
        params={"assistant_id": str(seed["bygg"])},
        headers=headers,
    )
    assert sidebar.status_code == 200, sidebar.text
    sidebar_ids = {item["id"] for item in sidebar.json()["items"]}
    assert str(seed["insight_session"]) not in sidebar_ids
    assert str(seed["s1"]) in sidebar_ids

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
    assert str(seed["insight_session"]) not in explore_ids
    assert str(seed["s1"]) in explore_ids
