# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import re
from dataclasses import replace
from typing import Any

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.assistants.assistant_service import REFERENCE_PATTERN
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

# A citation marker split across two text chunks is found in the tail of the
# previous chunk plus the next one.
_MARKER_TAIL = len('<inref id="00000000"/>') - 1


class VisitorView:
    """What an anonymous widget visitor may see of an answer.

    The one filter for every visitor-facing payload: the ask response and its
    stream, the restored session, and the session the feedback call returns.
    Shapes stay those of the ordinary conversation API and only values are
    cleared, so the embed page drives the same client code as the app.

    Never shown: the model record, reasoning, token counts, the assistant and
    Skills behind the answer, tool results and tool ``_meta``, and the raw
    content of tool resources. With ``show_sources`` off no reference of any kind leaves the server. With
    ``show_tool_activity`` off no tool call does. A resource a tool returned
    reaches the visitor only once the answer cites it, on a tool event with an
    empty tool list, so the stream carries what a restore does.

    One instance filters one answer stream: it holds the uncited resources.
    """

    def __init__(self, widget: Widget) -> None:
        self.widget = widget
        self._uncited: dict[str, McpToolReference] = {}
        self._tail = ""

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

    def events(self, chunk: Completion) -> list[Completion]:
        """The stream events a visitor gets for one pipeline event, in order."""
        if chunk.response_type in (
            ResponseType.REASONING,
            # Visitors are never asked to approve a tool.
            ResponseType.TOOL_APPROVAL_REQUIRED,
            ResponseType.TOOL_APPROVAL_TIMEOUT,
            # The widget shows no context meter; counts reveal prompt sizes.
            ResponseType.TOKEN_USAGE,
        ):
            return []
        if chunk.response_type == ResponseType.TOOL_CALL:
            return self._tool_events(chunk)
        if chunk.response_type == ResponseType.TEXT:
            cited = self._newly_cited(chunk.text or "")
            if not self.widget.show_sources and chunk.reference_chunks is not None:
                chunk = replace(chunk, reference_chunks=None)
            return [*cited, chunk]
        return [chunk]

    def _tool_events(self, chunk: Completion) -> list[Completion]:
        calls: list[ToolCallMetadata] = (
            [
                replace(call, result=None, meta=None)
                for call in chunk.tool_calls_metadata or []
            ]
            if self.widget.show_tool_activity
            else []
        )
        shown: list[McpToolReference] = []
        if self.widget.show_sources:
            for ref in chunk.mcp_tool_references or []:
                # Images cannot be cited and are kept on the answer as is.
                if (ref.mime_type or "").startswith("image/"):
                    shown.append(self._visible_reference(ref))
                else:
                    self._uncited.setdefault(str(ref.id)[:8], ref)
        if not calls and not shown:
            return []
        return [
            replace(
                chunk,
                tool_calls_metadata=calls or None,
                mcp_tool_references=shown or None,
            )
        ]

    def _newly_cited(self, text: str) -> list[Completion]:
        if not self._uncited or not text:
            self._tail = (self._tail + text)[-_MARKER_TAIL:]
            return []
        window = self._tail + text
        self._tail = window[-_MARKER_TAIL:]
        cited = [
            self._uncited.pop(short_id)
            for short_id in dict.fromkeys(re.findall(REFERENCE_PATTERN, window))
            if short_id in self._uncited
        ]
        if not cited:
            return []
        return [
            Completion(
                text="",
                response_type=ResponseType.TOOL_CALL,
                mcp_tool_references=[self._visible_reference(ref) for ref in cited],
            )
        ]

    def _visible_reference(self, ref: McpToolReference) -> McpToolReference:
        return replace(ref, **self._reference_changes(ref.meta))

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
                "num_tokens_question": 0,
                "num_tokens_answer": 0,
                "context_prompt_tokens": None,
                "context_completion_tokens": None,
                "skill_context_tokens": None,
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
