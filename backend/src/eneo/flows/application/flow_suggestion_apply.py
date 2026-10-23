"""Applying suggestions: the editor updates their patches describe, made on
the draft the suggestions hold for, all of them or none.

The caller names the suggestions by fingerprint and the revision it read
them at. They are applied in the order the suggestions are listed, each one
as an editor update (``apply_editor_update``) and nothing else writes: its
revision fence, read following, copy-on-write assistants, classification and
audit apply as for any editor change, and its audit entries name the
suggestion. After each fix the suggestions are computed again on the draft as
it is now, because two fixes may change the same prompt and a patch is built
from the text it changes. A suggestion an earlier fix of the batch made go
away is skipped and reported. Every refusal escapes, so the caller's
transaction rolls the whole batch back.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request

from eneo.flows.api.flow_definition_access import require_flow_edit_access
from eneo.flows.api.flow_models import FlowEditorUpdateRequest, FlowPublic
from eneo.flows.application.flow_authoring_operations import apply_editor_update
from eneo.flows.application.flow_service import published_draft_refusal
from eneo.flows.application.flow_suggestion_service import list_flow_suggestions
from eneo.flows.domain.flow_suggestions import FlowSuggestion
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_repo import stale_revision_error
from eneo.main.container.container import Container
from eneo.main.exceptions import ConflictException

SUGGESTION_ORIGIN = "suggestion"


@dataclass(frozen=True, slots=True)
class AppliedSuggestions:
    """The draft after the batch, the fingerprints whose fixes were applied
    and those an earlier fix of the batch made go away, each in the order
    they were taken."""

    flow: FlowPublic
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


async def apply_flow_suggestions(
    id: UUID,
    request: Request,
    *,
    fingerprints: Sequence[str],
    expected_revision: int,
    container: Container,
) -> AppliedSuggestions:
    """Apply the ``patch`` fixes of the draft's suggestions ``fingerprints``.

    Refused as the editor refuses a change (edit access, a published flow,
    a draft that has left ``expected_revision``), and with ``409`` when the
    draft does not have one of the suggestions (``flow_suggestion_stale``)
    or the fix of one is not a patch (``flow_suggestion_not_patchable``).
    The caller owns the transaction, as for ``apply_editor_update``, and
    rolls back every fix of the batch when one is refused."""

    access = await require_flow_edit_access(request, container, flow_id=id)
    flow = access.flow
    refusal = published_draft_refusal(flow)
    if refusal is not None:
        raise refusal
    if flow.draft_revision != expected_revision:
        raise stale_revision_error(flow_id=id, expected_revision=expected_revision)
    suggestions = await list_flow_suggestions(container=container, flow=flow)
    listed = {suggestion.fingerprint for suggestion in suggestions}
    missing = [fingerprint for fingerprint in fingerprints if fingerprint not in listed]
    if missing:
        raise _stale(missing)
    requested = set(fingerprints)
    chosen = [item for item in suggestions if item.fingerprint in requested]
    for suggestion in chosen:
        _require_patch(suggestion)
    order = [item.fingerprint for item in chosen]

    applied: list[str] = []
    skipped: list[str] = []
    revision = expected_revision
    updated: FlowPublic | None = None
    for fingerprint in order:
        if updated is not None:
            draft = await container.flow_service().get_flow(id)
            suggestions = await list_flow_suggestions(container=container, flow=draft)
        suggestion = next(
            (item for item in suggestions if item.fingerprint == fingerprint), None
        )
        if suggestion is None:
            # Listed when the batch began, so an earlier fix made it go.
            skipped.append(fingerprint)
            continue
        updated = await _apply(
            id, request, suggestion, revision=revision, container=container
        )
        revision = updated.draft_revision
        applied.append(fingerprint)
    assert updated is not None, "the first suggestion of a batch is always applied"
    return AppliedSuggestions(
        flow=updated, applied=tuple(applied), skipped=tuple(skipped)
    )


async def _apply(
    id: UUID,
    request: Request,
    suggestion: FlowSuggestion,
    *,
    revision: int,
    container: Container,
) -> FlowPublic:
    return await apply_editor_update(
        id,
        request,
        FlowEditorUpdateRequest.model_validate(
            {**_require_patch(suggestion), "expected_revision": revision}
        ),
        container,
        audit_context={
            "origin": SUGGESTION_ORIGIN,
            "suggestion_code": suggestion.code.value,
            "suggestion_fingerprint": suggestion.fingerprint,
        },
    )


def _require_patch(suggestion: FlowSuggestion) -> dict[str, Any]:
    """The suggestion's patch, refused when its fix is not one."""
    patch = suggestion.fix.patch
    if suggestion.fix.kind != "patch" or patch is None:
        raise ConflictException(
            "This suggestion has no fix that can be applied as it is. Make the "
            "change it describes in the editor.",
            code=FlowApiErrorCode.SUGGESTION_NOT_PATCHABLE.value,
            context={
                "fingerprint": suggestion.fingerprint,
                "suggestion_code": suggestion.code.value,
                "fix_kind": suggestion.fix.kind,
            },
        )
    return patch


def _stale(fingerprints: Sequence[str]) -> ConflictException:
    return ConflictException(
        "The draft no longer has this suggestion. Read the suggestions again.",
        code=FlowApiErrorCode.SUGGESTION_STALE.value,
        context={"fingerprint": fingerprints[0], "fingerprints": list(fingerprints)},
    )


__all__ = ["SUGGESTION_ORIGIN", "AppliedSuggestions", "apply_flow_suggestions"]
