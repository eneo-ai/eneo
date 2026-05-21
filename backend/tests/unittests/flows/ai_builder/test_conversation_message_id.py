"""Stability tests for ConversationMessage.message_id.

Downstream consumers reference conversation messages by stable ID rather
than by positional index (indices break after conversation compaction).
The contract this module locks in:

- Every newly constructed ConversationMessage has a UUIDv7 `message_id`.
- Two freshly constructed messages get distinct ids.
- `model_validate` preserves an existing `message_id` (round-trip stable).
- `from_persisted` rejects rows missing `message_id` — hard-migrate contract,
  no silent rescue.
- `_session_from_row` (repo boundary) propagates the rejection — the contract
  is enforced where it matters, not only on the domain model.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_repo import _session_from_row


def test_new_message_gets_auto_generated_uuidv7_message_id() -> None:
    msg = ConversationMessage(role="user", content="hi")

    assert isinstance(msg.message_id, str)
    assert UUID(msg.message_id).version == 7


def test_two_new_messages_have_distinct_message_ids() -> None:
    a = ConversationMessage(role="user", content="one")
    b = ConversationMessage(role="user", content="two")

    assert a.message_id != b.message_id


def test_model_validate_preserves_existing_message_id() -> None:
    msg = ConversationMessage.model_validate(
        {
            "role": "assistant",
            "content": "reply",
            "message_id": "019db164-9eab-7843-baa1-229e595cde04",
        }
    )

    assert msg.message_id == "019db164-9eab-7843-baa1-229e595cde04"


def test_from_persisted_rejects_row_without_message_id() -> None:
    with pytest.raises(ValueError, match="message_id"):
        ConversationMessage.from_persisted({"role": "user", "content": "legacy"})


def test_from_persisted_accepts_backfilled_row() -> None:
    msg = ConversationMessage.from_persisted(
        {
            "role": "user",
            "content": "backfilled legacy",
            "message_id": "00000000-0000-4000-8000-000000000001",
        }
    )

    assert msg.message_id == "00000000-0000-4000-8000-000000000001"


def test_model_dump_roundtrip_preserves_message_id() -> None:
    original = ConversationMessage(role="user", content="round trip")

    dumped = original.model_dump(mode="json")
    restored = ConversationMessage.model_validate(dumped)

    assert restored.message_id == original.message_id


def test_session_from_row_rejects_legacy_conversation_entry() -> None:
    row = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "space_id": uuid4(),
        "flow_id": None,
        "target_kind": "create",
        "status": "chatting",
        "actor_user_id": uuid4(),
        "conversation": [{"role": "user", "content": "legacy — no message_id"}],
        "active_request_id": None,
        "latest_plan_id": None,
        "created_at": None,
        "updated_at": None,
    }

    with pytest.raises(ValueError, match="message_id"):
        _session_from_row(row)


def test_session_from_row_accepts_backfilled_conversation_entry() -> None:
    backfilled_id = "00000000-0000-4000-8000-000000000002"
    row = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "space_id": uuid4(),
        "flow_id": None,
        "target_kind": "create",
        "status": "chatting",
        "actor_user_id": uuid4(),
        "conversation": [
            {
                "role": "user",
                "content": "backfilled",
                "message_id": backfilled_id,
            }
        ],
        "active_request_id": None,
        "latest_plan_id": None,
        "created_at": None,
        "updated_at": None,
    }

    session = _session_from_row(row)

    assert len(session.conversation) == 1
    assert session.conversation[0].message_id == backfilled_id
