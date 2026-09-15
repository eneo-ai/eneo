from __future__ import annotations

import pytest

from tests.unittests.flows.test_flow_review_checkpoint_router import (
    _call_history,
    _history_context,
)


@pytest.mark.asyncio
async def test_correction_revision_page_starts_empty_then_uses_preceding_revision(
    monkeypatch,
):
    container, ctx, repo, rows = _history_context(monkeypatch, corrections=True)
    first = await _call_history(container, ctx, corrections=True, limit=1)
    assert first.baseline.revision == 0
    assert first.baseline.occurrences_json == []
    assert first.baseline.speaker_edits_json == []
    assert first.next_after_revision == 1
    assert first.items[0].edited_by_service_principal.display_name == "History editor"
    later = await _call_history(container, ctx, corrections=True, after_revision=1)
    assert later.baseline.revision == 1
    assert later.baseline.occurrences_json == rows[0].occurrences_json
    assert [item.revision for item in later.items] == [2, 3]
    assert later.truncated is False
