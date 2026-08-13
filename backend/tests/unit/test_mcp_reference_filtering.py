from uuid import UUID, uuid4

from eneo.ai_models.completion_models.completion_model import McpToolReference
from eneo.assistants.assistant_service import filter_mcp_tool_references


def _ref(
    ref_id: UUID | None = None,
    *,
    uri: str = "eneo://info-blob/doc#chunk-0",
    mime_type: str | None = "text/plain",
    content: str | None = "passage",
    order: int = 0,
) -> McpToolReference:
    return McpToolReference(
        id=ref_id or uuid4(),
        tool_call_id="call_1",
        mcp_tool_name="server__tool",
        uri=uri,
        mime_type=mime_type,
        content=content,
        meta={},
        order=order,
    )


def _inref(ref: McpToolReference) -> str:
    return f'<inref id="{str(ref.id)[:8]}"/>'


def test_version_1_returns_all_references_unchanged():
    refs = [_ref(), _ref()]

    result = filter_mcp_tool_references(
        response_string="No citations here.", references=refs, version=1
    )

    assert result == refs


def test_version_2_keeps_only_cited_references():
    cited, uncited = _ref(), _ref()

    result = filter_mcp_tool_references(
        response_string=f"A fact.{_inref(cited)} And an uncited claim.",
        references=[uncited, cited],
        version=2,
    )

    assert result == [cited]


def test_version_2_orders_by_first_citation_appearance():
    first, second = _ref(), _ref()

    result = filter_mcp_tool_references(
        response_string=f"B first.{_inref(second)} Then A.{_inref(first)}",
        references=[first, second],
        version=2,
    )

    assert result == [second, first]


def test_duplicate_citations_yield_one_reference():
    ref = _ref()

    result = filter_mcp_tool_references(
        response_string=f"Twice.{_inref(ref)} Again.{_inref(ref)}",
        references=[ref],
        version=2,
    )

    assert result == [ref]


def test_unknown_citation_ids_are_ignored():
    ref = _ref()

    result = filter_mcp_tool_references(
        response_string='Cites nothing real.<inref id="deadbeef"/>',
        references=[ref],
        version=2,
    )

    assert result == []


def test_display_only_image_references_are_always_kept():
    image = _ref(
        uri="https://example.test/chart.png", mime_type="image/png", content=None
    )
    uncited_text = _ref()

    result = filter_mcp_tool_references(
        response_string="No citations at all.",
        references=[uncited_text, image],
        version=2,
    )

    assert result == [image]


def test_image_references_follow_cited_text_references():
    image = _ref(
        uri="https://example.test/chart.png", mime_type="image/png", content=None
    )
    cited = _ref()

    result = filter_mcp_tool_references(
        response_string=f"Cited.{_inref(cited)}",
        references=[image, cited],
        version=2,
    )

    assert result == [cited, image]
