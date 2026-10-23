"""Applying suggestions: the fresh patch of each one, as an editor update
naming the suggestion, in listing order, all of them or none."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_models import FlowEditorUpdateRequest
from eneo.flows.api.flow_suggestion_apply_models import FlowSuggestionsApplyRequest
from eneo.flows.application import flow_suggestion_apply
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionImpact,
)
from eneo.main.exceptions import BadRequestException, ConflictException

FLOW_ID = uuid4()
STEP_ID = uuid4()
ASSISTANT_ID = uuid4()


def _patch(text: str) -> dict[str, Any]:
    return {
        "definition": {},
        "assistants": [
            {
                "assistant_id": str(ASSISTANT_ID),
                "step_id": str(STEP_ID),
                "changes": {"prompt": {"text": text, "description": None}},
            }
        ],
    }


def _suggestion(
    fingerprint: str,
    *,
    patch: dict[str, Any] | None = None,
    kind: str = "patch",
    code: FlowSuggestionCode = FlowSuggestionCode.DUPLICATE_READ,
) -> FlowSuggestion:
    return FlowSuggestion(
        code=code,
        fingerprint=fingerprint,
        steps=(STEP_ID,),
        message="Step 2 reads step 1 twice.",
        impact=FlowSuggestionImpact(basis="definition", level="high"),
        fix=FlowSuggestionFix(
            kind=kind,  # pyright: ignore[reportArgumentType]
            patch=patch if kind == "patch" else None,
        ),
    )


class Draft:
    """The flow as each step of the batch loads it, and the editor updates
    it receives; each saved update advances the revision by one."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        listings: list[list[FlowSuggestion]],
        *,
        revision: int = 4,
        published_version: int | None = None,
    ) -> None:
        self.revision = revision
        self.listings = list(listings)
        self.updates: list[FlowEditorUpdateRequest] = []
        self.contexts: list[dict[str, str]] = []
        self.flow = SimpleNamespace(
            id=FLOW_ID, draft_revision=revision, published_version=published_version
        )
        self.container = MagicMock()
        self.container.flow_service.return_value.get_flow = AsyncMock(
            side_effect=lambda _id: self.flow
        )
        self.list = AsyncMock(side_effect=self._list)
        monkeypatch.setattr(
            flow_suggestion_apply,
            "require_flow_edit_access",
            AsyncMock(return_value=SimpleNamespace(flow=self.flow)),
        )
        monkeypatch.setattr(flow_suggestion_apply, "list_flow_suggestions", self.list)
        monkeypatch.setattr(
            flow_suggestion_apply,
            "apply_editor_update",
            AsyncMock(side_effect=self._save),
        )

    async def _list(self, *, container, flow):
        return tuple(self.listings.pop(0))

    async def _save(self, id: UUID, request, update, container, *, audit_context):
        assert update.expected_revision == self.flow.draft_revision
        self.updates.append(update)
        self.contexts.append(dict(audit_context))
        self.flow.draft_revision += 1
        return SimpleNamespace(draft_revision=self.flow.draft_revision)

    async def apply(self, *fingerprints: str, expected_revision: int | None = None):
        return await flow_suggestion_apply.apply_flow_suggestions(
            FLOW_ID,
            MagicMock(),
            fingerprints=list(fingerprints),
            expected_revision=(
                self.revision if expected_revision is None else expected_revision
            ),
            container=self.container,
        )


async def test_one_fix_is_the_editor_update_of_its_patch_naming_the_suggestion(
    monkeypatch,
):
    draft = Draft(monkeypatch, [[_suggestion("a", patch=_patch("Sammanfatta."))]])

    result = await draft.apply("a")

    assert draft.updates == [
        FlowEditorUpdateRequest.model_validate(
            {**_patch("Sammanfatta."), "expected_revision": 4}
        )
    ]
    assert draft.contexts == [
        {
            "origin": "suggestion",
            "suggestion_code": "duplicate_read",
            "suggestion_fingerprint": "a",
        }
    ]
    assert result.applied == ("a",)
    assert result.skipped == ()
    assert result.flow.draft_revision == 5


async def test_a_fingerprint_the_draft_does_not_have_refuses_the_batch(monkeypatch):
    draft = Draft(monkeypatch, [[_suggestion("a", patch=_patch("x"))]])

    with pytest.raises(ConflictException) as refused:
        await draft.apply("a", "gone")

    assert refused.value.code == "flow_suggestion_stale"
    assert refused.value.context == {"fingerprint": "gone", "fingerprints": ["gone"]}
    assert draft.updates == []


async def test_a_fix_that_is_not_a_patch_refuses_the_batch_before_any_write(
    monkeypatch,
):
    draft = Draft(
        monkeypatch,
        [
            [
                _suggestion("a", patch=_patch("x")),
                _suggestion(
                    "b",
                    kind="assisted",
                    code=FlowSuggestionCode.WHOLE_STRUCTURED_READ,
                ),
            ]
        ],
    )

    with pytest.raises(ConflictException) as refused:
        await draft.apply("a", "b")

    assert refused.value.code == "flow_suggestion_not_patchable"
    assert refused.value.context == {
        "fingerprint": "b",
        "suggestion_code": "whole_structured_read",
        "fix_kind": "assisted",
    }
    assert draft.updates == []


async def test_a_draft_that_left_the_revision_is_the_editors_conflict(monkeypatch):
    draft = Draft(monkeypatch, [[_suggestion("a", patch=_patch("x"))]])

    with pytest.raises(BadRequestException) as refused:
        await draft.apply("a", expected_revision=3)

    assert refused.value.code == "stale_revision"
    draft.list.assert_not_awaited()
    assert draft.updates == []


async def test_a_published_flow_must_be_unpublished_first(monkeypatch):
    draft = Draft(
        monkeypatch, [[_suggestion("a", patch=_patch("x"))]], published_version=1
    )

    with pytest.raises(BadRequestException) as refused:
        await draft.apply("a")

    assert refused.value.code == "flow_unpublish_required"
    assert draft.updates == []


async def test_each_fix_uses_the_patch_computed_after_the_one_before(monkeypatch):
    # Two fixes of one prompt: the second patch is built from the text the
    # first one saved, so both land.
    draft = Draft(
        monkeypatch,
        [
            [
                _suggestion("first", patch=_patch("A\nB")),
                _suggestion("second", patch=_patch("A\nB\nC")),
            ],
            [_suggestion("second", patch=_patch("A"))],
        ],
    )

    # Applied in listing order, whatever the order asked for.
    result = await draft.apply("second", "first")

    assert [update.assistants[0].changes.prompt.text for update in draft.updates] == [
        "A\nB",
        "A",
    ]
    assert [update.expected_revision for update in draft.updates] == [4, 5]
    assert [context["suggestion_fingerprint"] for context in draft.contexts] == [
        "first",
        "second",
    ]
    assert result.applied == ("first", "second")
    assert result.flow.draft_revision == 6


async def test_a_suggestion_an_earlier_fix_resolved_is_skipped(monkeypatch):
    draft = Draft(
        monkeypatch,
        [
            [
                _suggestion("first", patch=_patch("A")),
                _suggestion("second", patch=_patch("A\nB")),
            ],
            [],
        ],
    )

    result = await draft.apply("first", "second")

    assert len(draft.updates) == 1
    assert result.applied == ("first",)
    assert result.skipped == ("second",)


async def test_a_fix_an_earlier_one_made_unpatchable_refuses_the_batch(monkeypatch):
    # The caller's transaction rolls back the fix already made.
    draft = Draft(
        monkeypatch,
        [
            [
                _suggestion("first", patch=_patch("A")),
                _suggestion("second", patch=_patch("A\nB")),
            ],
            [_suggestion("second", kind="assisted")],
        ],
    )

    with pytest.raises(ConflictException) as refused:
        await draft.apply("first", "second")

    assert refused.value.code == "flow_suggestion_not_patchable"


@pytest.mark.parametrize(
    "fingerprints",
    [[], ["a", "a"], [f"f{index}" for index in range(51)], [""]],
    ids=["none", "repeated", "too_many", "empty"],
)
def test_the_request_names_one_to_fifty_suggestions_once(fingerprints):
    with pytest.raises(ValidationError):
        FlowSuggestionsApplyRequest.model_validate(
            {"expected_revision": 4, "fingerprints": fingerprints}
        )
