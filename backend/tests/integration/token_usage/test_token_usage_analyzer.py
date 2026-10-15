"""Per-model token statistics count what a reader model spent inside digest
tool calls, from the call's ``_meta``, and only for calls Eneo's own servers
made."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.token_usage.infrastructure.token_usage_analyzer import TokenUsageAnalyzer


def _digest_call(
    reader_model_id, *, is_internal: bool, tokens_in=300_000, tokens_out=10_000
):
    return {
        "server_name": "knowledge",
        "tool_name": "digest_documents",
        "mcp_tool_name": "knowledge__digest_documents",
        "result_status": "succeeded",
        "is_internal": is_internal,
        "meta": {
            "gen_ai.request.model": "turn",
            "gen_ai.usage.input_tokens": 10_000,
            "gen_ai.usage.output_tokens": 3_000,
            "eneo.reader_model_id": str(reader_model_id),
            "eneo.reader.model": "reader",
            "eneo.reader.input_tokens": tokens_in,
            "eneo.reader.output_tokens": tokens_out,
        },
    }


async def test_reader_share_is_counted_on_the_reader_model_from_internal_calls(
    async_session: AsyncSession,
    admin_user,
    test_tenant,
    completion_model_factory,
) -> None:
    turn = await completion_model_factory(async_session, "turn")
    reader = await completion_model_factory(async_session, "reader")
    chat = Sessions(user_id=admin_user.id, name="Digest chat")
    async_session.add(chat)
    await async_session.flush()

    async_session.add_all(
        [
            # The turn's share is folded into the row; the reader's is in the
            # call's meta only.
            Questions(
                question="Vilka beslut?",
                answer="Lista",
                num_tokens_question=28_000,
                num_tokens_answer=6_000,
                tenant_id=test_tenant.id,
                session_id=chat.id,
                completion_model_id=turn.id,
                tool_calls=[
                    {"server_name": "knowledge", "tool_name": "list_knowledge_sources"},
                    _digest_call(reader.id, is_internal=True),
                ],
            ),
            # An external server reporting the same keys is not believed.
            Questions(
                question="Forged",
                answer="",
                num_tokens_question=10,
                num_tokens_answer=5,
                tenant_id=test_tenant.id,
                session_id=chat.id,
                completion_model_id=turn.id,
                tool_calls=[
                    _digest_call(reader.id, is_internal=False, tokens_in=999_999)
                ],
            ),
            # A row with no tool calls at all.
            Questions(
                question="Hej",
                answer="Hej!",
                num_tokens_question=20,
                num_tokens_answer=8,
                tenant_id=test_tenant.id,
                session_id=chat.id,
                completion_model_id=turn.id,
            ),
        ]
    )
    await async_session.flush()

    now = datetime.now(timezone.utc)
    summary = await TokenUsageAnalyzer(async_session).get_model_token_usage(
        test_tenant.id, now - timedelta(days=1), now + timedelta(days=1)
    )

    by_id = {usage.model_id: usage for usage in summary.models}
    assert by_id[turn.id].input_token_usage == 28_030
    assert by_id[turn.id].output_token_usage == 6_013
    assert by_id[turn.id].request_count == 3
    assert by_id[turn.id].reader_token_usage == 0
    assert by_id[reader.id].input_token_usage == 300_000
    assert by_id[reader.id].output_token_usage == 10_000
    assert by_id[reader.id].reader_input_token_usage == 300_000
    assert by_id[reader.id].reader_output_token_usage == 10_000
    assert by_id[reader.id].request_count == 1
    assert summary.total_token_usage == 28_030 + 6_013 + 310_000
