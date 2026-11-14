"""An assistant's answer as the connector protocol's events.

The protocol's ask stream is small: the answer's text as it is written, then
the sources the answer cites, then one closing event.

    {"type": "text", "delta": "..."}
    {"type": "source", "source": {"label": "...", "link": "https://..."}}
    {"type": "done", "session": "<uuid>", "link": "https://..."}
    {"type": "handback", "reason": "declined", "session": "<uuid>"}
    {"type": "handback", "reason": "completed", "session": "<uuid>", "link": "..."}
    {"type": "error", "code": "unavailable"}

Eneo's answers carry citation tags (``<inref id="1a2b3c4d"/>``) where a source
is used. The calling system shows plain text, so the tags are taken out, and
the sources they point at are listed once each, in the order cited. A source
that was retrieved but never cited is not listed. Reasoning, tool activity and
token counts stay in Eneo.

An assistant can return the conversation to the calling system by calling the
handback tool (``eneo.internal_mcp.handback``). The stream then ends with
``handback`` instead of ``done``: ``declined`` when the question was not the
assistant's to answer, after which nothing more of the answer is sent, or
``completed`` after an answer the assistant considers the end of the matter.
A handback carries the reason, the session and the link, and no text.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
)
from eneo.info_blobs.info_blob import InfoBlobAskAssistantPublic, InfoBlobMetadata
from eneo.internal_mcp.constants import HANDBACK_SERVER_NAME
from eneo.internal_mcp.handback import HAND_BACK_TOOL_NAME, HANDBACK_REASONS
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.assistants.api.assistant_models import AssistantResponse

logger = get_logger(__name__)

MAX_TEXT_DELTA = 4000
MAX_SOURCES = 10
MAX_LABEL = 300
MAX_LINK = 2000
# The calling system stops reading after three minutes; end a little earlier
# so the answer closes with an event of its own.
ANSWER_DEADLINE_SECONDS = 170
UNTITLED = "Dokument utan titel"

_TAG = re.compile(r'<inref id="([0-9a-f]+)"\s*/>')
# The start of a citation tag, cut anywhere before its end.
_PARTIAL_TAG = re.compile(
    r'<(?:i(?:n(?:r(?:e(?:f(?: (?:i(?:d(?:=(?:"(?:[0-9a-f]*(?:"(?:\s*/?)?)?)?)?)?)?)?)?)?)?)?)?)?'
)
_HTTPS_LINK = re.compile(r"https://\S+")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _source(title: object, url: object) -> dict[str, str]:
    source = {
        "label": _clip(
            title if isinstance(title, str) and title else UNTITLED, MAX_LABEL
        )
    }
    if isinstance(url, str) and len(url) <= MAX_LINK and _HTTPS_LINK.fullmatch(url):
        source["link"] = url
    return source


class CitedText:
    """Takes the citation tags out of text that arrives in pieces.

    ``feed`` returns what can be shown now. A tail that may still become a tag
    is held back until the next piece decides it; ``flush`` returns a tail that
    never became one. ``cited`` lists the ids the tags named, each once, in
    the order they appeared.
    """

    def __init__(self) -> None:
        self._held = ""
        self.cited: list[str] = []

    def _cite(self, match: re.Match[str]) -> str:
        if match[1] not in self.cited:
            self.cited.append(match[1])
        return ""

    def feed(self, delta: str) -> str:
        text = _TAG.sub(self._cite, self._held + delta)
        at = text.rfind("<")
        if at >= 0 and _PARTIAL_TAG.fullmatch(text[at:]):
            self._held = text[at:]
            return text[:at]
        self._held = ""
        return text

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


class _Sources:
    """Everything the answer could cite, by Eneo's id."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, str]] = {}

    def add_blob(self, blob: Any) -> None:
        # The same reading of a retrieved document as Eneo's own answer stream.
        public = InfoBlobAskAssistantPublic(
            **blob.model_dump(), metadata=InfoBlobMetadata(**blob.model_dump())
        )
        self._by_id.setdefault(
            str(public.id), _source(public.metadata.title, public.metadata.url)
        )

    def add_reference(self, reference: Any) -> None:
        raw: object = reference.meta
        meta = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
        self._by_id.setdefault(
            str(reference.id), _source(meta.get("title"), meta.get("url"))
        )

    def cited(self, prefixes: list[str]) -> list[dict[str, str]]:
        """The sources the tags point at: a tag carries the start of an id."""
        found: list[str] = []
        for prefix in prefixes:
            full = next((key for key in self._by_id if key.startswith(prefix)), None)
            if full is not None and full not in found:
                found.append(full)
        return [self._by_id[key] for key in found[:MAX_SOURCES]]


def _handback_reason(completion: Completion) -> str | None:
    """The reason the assistant gave if this chunk shows it handing back.

    Only a call routed to Eneo's own handback server counts: an external
    server an administrator named alike, or a call whose arguments are not
    written yet, does not.
    """
    for tool in completion.tool_calls_metadata or []:
        if (
            tool.is_internal is True
            and tool.server_name == HANDBACK_SERVER_NAME
            and tool.tool_name == HAND_BACK_TOOL_NAME
            and tool.approved is not False
        ):
            reason = (tool.arguments or {}).get("reason")
            if isinstance(reason, str) and reason in HANDBACK_REASONS:
                return reason
    return None


def _text_events(text: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "delta": text[start : start + MAX_TEXT_DELTA]}
        for start in range(0, len(text), MAX_TEXT_DELTA)
    ]


async def answer_events(
    response: "AssistantResponse",
    *,
    link: str | None,
    deadline_seconds: float = ANSWER_DEADLINE_SECONDS,
) -> AsyncIterator[dict[str, Any]]:
    """The events of one streamed answer, ending in ``done``, ``handback`` or
    ``error``.

    ``link`` opens the same conversation in Eneo's own interface; None when the
    installation has no public https address.
    """
    assert not isinstance(response.answer, str)
    sources = _Sources()
    for blob in response.info_blobs:
        sources.add_blob(blob)

    text = CitedText()
    written = ""  # the tail of what was sent, to join later rounds to it
    between_rounds = False
    handback: str | None = None
    try:
        async with asyncio.timeout(deadline_seconds):
            async for completion in response.answer:
                kind = completion.response_type
                if kind == ResponseType.ERROR:
                    yield {"type": "error", "code": "unavailable"}
                    return
                if kind == ResponseType.TEXT:
                    for blob in completion.reference_chunks or []:
                        sources.add_blob(blob)
                    if handback == "declined":
                        # The other system answers instead: whatever the
                        # model still writes stays in Eneo. The answer is
                        # read to its end so the turn is stored whole.
                        continue
                    visible = text.feed(completion.text or "")
                    # A later round of the model continues the same answer:
                    # keep it apart from what came before the tools ran.
                    if (
                        visible
                        and between_rounds
                        and written
                        and not written.endswith("\n")
                        and not visible.startswith("\n")
                    ):
                        visible = "\n\n" + visible
                    if visible:
                        between_rounds = False
                        written = visible[-1:]
                        for event in _text_events(visible):
                            yield event
                    continue
                if kind == ResponseType.TOOL_CALL:
                    for reference in completion.mcp_tool_references or []:
                        sources.add_reference(reference)
                    # A decline is final; a later "completed" cannot undo it.
                    if handback != "declined":
                        handback = _handback_reason(completion) or handback
                if kind in (ResponseType.TOOL_CALL, ResponseType.REASONING):
                    between_rounds = True
    except TimeoutError:
        yield {"type": "error", "code": "unavailable"}
        return
    except asyncio.CancelledError:
        # The caller stopped reading: nothing more to say, and the stream's
        # owner closes the completion.
        raise
    except Exception:
        logger.exception("An answer for a calling installation failed")
        yield {"type": "error", "code": "unknown"}
        return

    if handback != "declined":
        for event in _text_events(text.flush()):
            yield event
        for source in sources.cited(text.cited):
            yield {"type": "source", "source": source}
    closing: dict[str, Any] = (
        {"type": "done"}
        if handback is None
        else {"type": "handback", "reason": handback}
    )
    closing["session"] = str(response.session.id)
    if link is not None:
        closing["link"] = link
    yield closing
