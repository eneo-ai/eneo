"""An assistant's answer as the connector protocol's events: plain text, the
sources it cites, and one closing event."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from eneo.ai_models.completion_models.completion_model import Completion, ResponseType
from eneo.connector_protocol.answer_events import CitedText, answer_events

SESSION = UUID("11111111-1111-4111-8111-111111111111")
RULES = UUID("1a2b3c4d-0000-4000-8000-000000000001")
POLICY = UUID("5e6f7a8b-0000-4000-8000-000000000002")
LINK = f"https://eneo.example/dashboard/a/{SESSION}"


class _Blob:
    """A retrieved document, as far as the stream reads one."""

    def __init__(self, id: UUID, title: str | None, url: str | None = None) -> None:
        self.id, self.title, self.url = id, title, url

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "score": 0.9,
            "text": "",
            "embedding_model_id": UUID(int=1),
            "size": 10,
            "original_available": False,
        }


def _text(text: str, *blobs: _Blob) -> Completion:
    return Completion(
        text=text,
        response_type=ResponseType.TEXT,
        reference_chunks=list(blobs) or None,  # type: ignore[arg-type]
    )


def _response(*chunks: Completion, blobs: tuple[_Blob, ...] = ()) -> Any:
    async def answer() -> AsyncIterator[Completion]:
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(
        answer=answer(), info_blobs=list(blobs), session=SimpleNamespace(id=SESSION)
    )


async def _events(response: Any, **kwargs: Any) -> list[dict[str, Any]]:
    kwargs.setdefault("link", LINK)
    return [event async for event in answer_events(response, **kwargs)]


def _written(events: list[dict[str, Any]]) -> str:
    return "".join(event["delta"] for event in events if event["type"] == "text")


async def test_text_then_done_with_the_session_and_the_link():
    events = await _events(_response(_text("Du har "), _text("25 dagar.")))

    assert events == [
        {"type": "text", "delta": "Du har "},
        {"type": "text", "delta": "25 dagar."},
        {"type": "done", "session": str(SESSION), "link": LINK},
    ]


async def test_done_carries_no_link_without_a_public_address():
    events = await _events(_response(_text("Hej")), link=None)

    assert events[-1] == {"type": "done", "session": str(SESSION)}


async def test_citation_tags_are_removed_and_their_sources_listed_in_order_cited():
    rules = _Blob(RULES, "Semesterregler", "https://intra.example/semester")
    policy = _Blob(POLICY, "Personalpolicy")
    unused = _Blob(UUID(int=7), "Aldrig citerad", "https://intra.example/x")

    events = await _events(
        _response(
            _text('Enligt policyn <inref id="5e6f7a8b"/> och '),
            _text('reglerna <inref id="1a2b3c4d"/> gäller 25 dagar '),
            _text('<inref id="5e6f7a8b"/>.'),
            blobs=(rules, policy, unused),
        )
    )

    assert _written(events) == "Enligt policyn  och reglerna  gäller 25 dagar ."
    assert [event["source"] for event in events if event["type"] == "source"] == [
        {"label": "Personalpolicy"},
        {"label": "Semesterregler", "link": "https://intra.example/semester"},
    ]
    assert events[-1]["type"] == "done"


async def test_a_tag_split_across_chunks_never_shows():
    rules = _Blob(RULES, "Semesterregler")

    events = await _events(
        _response(
            _text("Se reglerna <in"),
            _text('ref id="1a2b'),
            _text('3c4d"'),
            _text("/> för mer."),
            blobs=(rules,),
        )
    )

    assert _written(events) == "Se reglerna  för mer."
    assert all("<" not in e["delta"] for e in events if e["type"] == "text")
    assert {"type": "source", "source": {"label": "Semesterregler"}} in events


async def test_an_angle_bracket_that_is_not_a_tag_is_text():
    events = await _events(_response(_text("a < b och <i"), _text("talic> och 3 <")))

    assert _written(events) == "a < b och <italic> och 3 <"


async def test_sources_found_while_answering_can_be_cited():
    found = _Blob(RULES, "Hittad under svaret")
    reference = SimpleNamespace(
        id=POLICY, meta={"title": "Från ett verktyg", "url": "https://tool.example/a"}
    )

    events = await _events(
        _response(
            Completion(
                response_type=ResponseType.TOOL_CALL,
                mcp_tool_references=[reference],  # type: ignore[list-item]
            ),
            _text('Svar <inref id="1a2b3c4d"/><inref id="5e6f7a8b"/>', found),
        )
    )

    assert [event["source"] for event in events if event["type"] == "source"] == [
        {"label": "Hittad under svaret"},
        {"label": "Från ett verktyg", "link": "https://tool.example/a"},
    ]


async def test_a_source_link_is_only_an_https_address():
    blobs = (
        _Blob(RULES, None, "http://intra.example/semester"),
        _Blob(POLICY, "T" * 400, "https://intra.example/with space"),
    )

    events = await _events(
        _response(_text('<inref id="1a2b3c4d"/><inref id="5e6f7a8b"/>ok'), blobs=blobs)
    )

    sources = [event["source"] for event in events if event["type"] == "source"]
    assert sources[0] == {"label": "Dokument utan titel"}
    assert set(sources[1]) == {"label"}
    assert len(sources[1]["label"]) == 300


async def test_at_most_ten_sources_are_listed():
    blobs = tuple(_Blob(UUID(int=(i + 1) << 96), f"Källa {i}") for i in range(12))
    tags = "".join(f'<inref id="{str(blob.id)[:8]}"/>' for blob in blobs)

    events = await _events(_response(_text(tags + "ok"), blobs=blobs))

    assert len([event for event in events if event["type"] == "source"]) == 10


async def test_long_text_is_cut_into_deltas_the_protocol_takes():
    events = await _events(_response(_text("å" * 9000)))

    deltas = [event["delta"] for event in events if event["type"] == "text"]
    assert [len(delta) for delta in deltas] == [4000, 4000, 1000]


async def test_text_after_a_tool_round_starts_a_new_paragraph():
    events = await _events(
        _response(
            _text("Jag kollar."),
            Completion(response_type=ResponseType.TOOL_CALL),
            _text("Det blev 25."),
            Completion(response_type=ResponseType.REASONING, reasoning_content="hm"),
            _text("\n\nKlart."),
        )
    )

    assert _written(events) == "Jag kollar.\n\nDet blev 25.\n\nKlart."


async def test_reasoning_tools_and_usage_stay_in_eneo():
    events = await _events(
        _response(
            Completion(
                response_type=ResponseType.REASONING, reasoning_content="hemligt"
            ),
            Completion(response_type=ResponseType.TOKEN_USAGE),
            _text("Svar"),
        )
    )

    assert [event["type"] for event in events] == ["text", "done"]


async def test_a_provider_error_ends_the_stream_with_one_error():
    events = await _events(
        _response(
            _text("Början"),
            Completion(response_type=ResponseType.ERROR, error="provider said no"),
            _text("aldrig"),
        )
    )

    assert events == [
        {"type": "text", "delta": "Början"},
        {"type": "error", "code": "unavailable"},
    ]


async def test_a_failure_while_answering_says_nothing_of_its_cause():
    async def answer() -> AsyncIterator[Completion]:
        yield _text("Början")
        raise RuntimeError("database password is hunter2")

    response = SimpleNamespace(
        answer=answer(), info_blobs=[], session=SimpleNamespace(id=SESSION)
    )

    events = await _events(response)

    assert events[-1] == {"type": "error", "code": "unknown"}
    assert "hunter2" not in str(events)


async def test_an_answer_that_takes_too_long_ends_as_unavailable():
    async def answer() -> AsyncIterator[Completion]:
        yield _text("Början")
        await asyncio.sleep(5)
        yield _text("aldrig")

    response = SimpleNamespace(
        answer=answer(), info_blobs=[], session=SimpleNamespace(id=SESSION)
    )

    events = await _events(response, deadline_seconds=0.05)

    assert events == [
        {"type": "text", "delta": "Början"},
        {"type": "error", "code": "unavailable"},
    ]


@pytest.mark.parametrize(
    "pieces",
    [
        ['<inref id="1a2b3c4d"/>'],
        ["<", "inref", ' id="', "1a2b3c4d", '"', " ", "/", ">"],
        ['<inref id="1a2b3c4d" />'],
    ],
)
def test_cited_text_reads_a_tag_however_it_is_cut(pieces):
    text = CitedText()

    shown = "".join(text.feed(piece) for piece in ["före ", *pieces, " efter"])

    assert shown + text.flush() == "före  efter"
    assert text.cited == ["1a2b3c4d"]


def test_cited_text_gives_back_a_tail_that_never_became_a_tag():
    text = CitedText()

    assert text.feed('slut <inref id="1a') == "slut "
    assert text.flush() == '<inref id="1a'
    assert text.cited == []
