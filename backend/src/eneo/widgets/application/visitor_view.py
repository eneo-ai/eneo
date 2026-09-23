# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import replace
from typing import Any, Optional

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.questions.question import (
    McpToolReferencePublic,
    Question,
    ToolCallInfo,
    UseTools,
)
from eneo.sessions.session import SessionInDB
from eneo.widgets.domain.widget import Widget

# The keys of a resource's `_meta` that clients render: a title, the kind of
# source and where in it the passage sits. Anything else a server put there
# is implementation detail.
DISPLAY_META_KEYS = frozenset({"title", "sourceType", "pageRange", "section"})


class VisitorView:
    """What an anonymous widget visitor may see of an answer.

    The one filter for every visitor-facing payload: the ask response and its
    stream, the restored session, and the session the feedback call returns.
    Shapes stay those of the ordinary conversation API and only values are
    cleared, so the embed page drives the same client code as the app.

    Never shown: the model record, reasoning, the assistant and Skills behind
    the answer, tool results and tool ``_meta``, and the raw content of tool
    resources. With ``show_sources`` off no reference of any kind leaves the
    server. With ``show_tool_activity`` off no tool call does, but resources a
    tool returned still reach the visitor as sources (on a tool event with an
    empty tool list) when sources are shown.
    """

    def __init__(self, widget: Widget) -> None:
        self.widget = widget

    # --- ask ----------------------------------------------------------------

    def response(self, response: AssistantResponse) -> AssistantResponse:
        """The first-chunk part of an ask response.

        Retrieved documents are never listed up front: the cited ones arrive
        with the answer text, and only when sources are shown.
        """
        return response.model_copy(
            update={
                "completion_model": None,
                "info_blobs": [],
                "tools": UseTools(assistants=[]),
                "mcp_tool_references": [],
                "description": None,
            }
        )

    def chunk(self, chunk: Completion) -> Optional[Completion]:
        """A stream event as the visitor gets it, or None to drop it."""
        if chunk.response_type in (
            ResponseType.REASONING,
            # Visitors are never asked to approve a tool.
            ResponseType.TOOL_APPROVAL_REQUIRED,
            ResponseType.TOOL_APPROVAL_TIMEOUT,
        ):
            return None
        if chunk.response_type == ResponseType.TOOL_CALL:
            calls: list[ToolCallMetadata] = (
                [
                    replace(call, result=None, meta=None)
                    for call in chunk.tool_calls_metadata or []
                ]
                if self.widget.show_tool_activity
                else []
            )
            references: list[McpToolReference] = (
                [
                    replace(ref, **self._reference_changes(ref.meta))
                    for ref in chunk.mcp_tool_references or []
                ]
                if self.widget.show_sources
                else []
            )
            if not calls and not references:
                return None
            return replace(
                chunk,
                tool_calls_metadata=calls or None,
                mcp_tool_references=references or None,
            )
        if not self.widget.show_sources and chunk.reference_chunks is not None:
            return replace(chunk, reference_chunks=None)
        return chunk

    # --- sessions -----------------------------------------------------------

    def session(self, session: SessionInDB) -> SessionInDB:
        return session.model_copy(
            update={"questions": [self._question(q) for q in session.questions]}
        )

    def _question(self, question: Question) -> Question:
        show_sources = self.widget.show_sources
        return question.model_copy(
            update={
                "completion_model": None,
                "reasoning": None,
                "skill_provenance": None,
                "skill_activation": None,
                "logging_details": None,
                # Without them the message's tools name no assistant.
                "assistant_id": None,
                "assistant_name": None,
                "info_blobs": question.info_blobs if show_sources else [],
                "mcp_tool_references": (
                    [
                        self._stored_reference(ref)
                        for ref in question.mcp_tool_references
                    ]
                    if show_sources
                    else []
                ),
                "tool_calls": (
                    [self._stored_call(call) for call in question.tool_calls or []]
                    if self.widget.show_tool_activity
                    else None
                ),
            }
        )

    @staticmethod
    def _stored_call(call: ToolCallInfo) -> ToolCallInfo:
        return call.model_copy(
            update={"result": None, "meta": None, "generated_file_ids": None}
        )

    def _stored_reference(self, ref: McpToolReferencePublic) -> McpToolReferencePublic:
        return ref.model_copy(update=self._reference_changes(ref.meta))

    # --- shared -------------------------------------------------------------

    def _reference_changes(self, meta: dict[str, Any]) -> dict[str, Any]:
        """One rule for a tool resource, streamed or restored: its title and
        link stay, its content does not, and with tool activity hidden
        nothing ties it to the call that produced it."""
        changes: dict[str, Any] = {
            "content": None,
            "meta": {key: meta[key] for key in meta if key in DISPLAY_META_KEYS},
        }
        if not self.widget.show_tool_activity:
            changes["tool_call_id"] = None
            changes["mcp_tool_name"] = None
        return changes
