"""Unit tests for the session proof export.

The invariants: the export is a self-contained document — unlike the
conversation payload it retains full tool-call results, attaches the captured
provider payload for logged turns (None-safe for uncaptured ones), preserves
message order, and stamps who exported it and when.
"""

from datetime import datetime, timezone
from uuid import uuid4

# SessionInDB's AssistantSparse forward ref is rebuilt by this module's import.
import eneo.assistants.api.assistant_models  # noqa: F401
from eneo.logging.logging import LoggingDetailsInDB
from eneo.questions.question import Question, ToolCallInfo
from eneo.sessions.session import SessionInDB
from eneo.sessions.session_protocol import to_session_debug_export

EXPORTED_AT = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _question(question: str, **overrides):
    defaults = dict(
        id=uuid4(),
        question=question,
        answer=f"Answer to {question}",
        num_tokens_question=10,
        num_tokens_answer=20,
        tenant_id=uuid4(),
        session_id=uuid4(),
    )
    defaults.update(overrides)
    return Question(**defaults)


def _session(questions: list[Question], **overrides):
    defaults = dict(
        id=uuid4(),
        name="Test session",
        user_id=uuid4(),
        questions=questions,
    )
    defaults.update(overrides)
    return SessionInDB(**defaults)


class TestSessionDebugExport:
    def test_tool_call_results_are_retained(self):
        tool_call = ToolCallInfo(
            server_name="tavily",
            tool_name="tavily_search",
            tool_call_id="call-1",
            result="full upstream result text",
        )
        session = _session([_question("q1", tool_calls=[tool_call])])

        export = to_session_debug_export(
            session, exported_by="anna@kommun.se", exported_at=EXPORTED_AT
        )

        assert export.messages[0].tool_calls[0].result == "full upstream result text"

    def test_logged_turn_carries_provider_payload(self):
        logging_details = LoggingDetailsInDB(
            id=uuid4(),
            model_kwargs={"temperature": 0.4},
            json_body='[{"role": "system", "content": "You are helpful."}]',
        )
        session = _session([_question("q1", logging_details=logging_details)])

        export = to_session_debug_export(
            session, exported_by="anna@kommun.se", exported_at=EXPORTED_AT
        )

        details = export.messages[0].logging_details
        assert details is not None
        assert details.model_kwargs == {"temperature": 0.4}
        assert details.json_body == [{"role": "system", "content": "You are helpful."}]

    def test_uncaptured_turn_exports_without_payload(self):
        # Un-captured turns persist an empty logging row (json_body null);
        # both that and a missing row must export as not logged.
        empty_row = LoggingDetailsInDB(id=uuid4(), model_kwargs={}, json_body=None)
        session = _session(
            [_question("q1"), _question("q2", logging_details=empty_row)]
        )

        export = to_session_debug_export(
            session, exported_by="anna@kommun.se", exported_at=EXPORTED_AT
        )

        assert export.messages[0].logging_details is None
        assert export.messages[1].logging_details is None

    def test_message_order_and_export_stamp(self):
        session = _session([_question("first"), _question("second")])

        export = to_session_debug_export(
            session, exported_by="anna@kommun.se", exported_at=EXPORTED_AT
        )

        assert [message.question for message in export.messages] == [
            "first",
            "second",
        ]
        assert export.exported_by == "anna@kommun.se"
        assert export.exported_at == EXPORTED_AT
        assert export.id == session.id

    def test_assistant_identity_included_when_present(self):
        session = _session([_question("q1")])
        export = to_session_debug_export(
            session, exported_by="anna@kommun.se", exported_at=EXPORTED_AT
        )
        assert export.assistant is None
