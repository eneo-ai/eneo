"""The space's MCP tools as the Builder's planner sees them: the usable ones
in a stable order inside fixed budgets, the refused ones kept aside with the
refusal that names why."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    build_proposal_prepared,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    outbound_proposal_tool_schemas,
    proposal_turn_tool_schemas,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    RESOURCE_DESCRIPTION_MAX_CHARS,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderPlannedRequestBudget
from eneo.flows.ai_builder.ai_builder_tool_catalog import (
    TOOL_CATALOG_OVERVIEW_MAX_CHARS,
    TOOL_CATALOG_SCHEMA_MAX_CHARS,
    AIBuilderToolCatalogProjection,
    fit_tool_catalog_projection,
    render_tool_catalog_block,
)
from eneo.flows.ai_builder.ai_builder_tools import build_propose_flow_tool_schema
from eneo.flows.application.flow_tool_options import (
    FlowToolOption,
    FlowToolOptions,
    FlowToolOptionsOverBound,
    SpaceToolOptions,
)
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal
from eneo.tokens.token_utils import count_tool_tokens
from tests.unittests.flows.ai_builder.test_ai_builder_planner import (
    _budget_policy,
    _document_architecture_state,
)
from tests.unittests.flows.ai_builder.test_ai_builder_tool_questions import (
    conversation_using_tools,
)


def _option(
    server: str,
    tool: str,
    *,
    refusal: UnattendedToolRefusal | None = None,
    description: str | None = None,
    schema: dict[str, object] | None = None,
    level: int | None = None,
) -> FlowToolOption:
    return FlowToolOption(
        mcp_server_id=uuid4(),
        mcp_server_name=server,
        mcp_server_security_level=level,
        tool_id=uuid4(),
        tool_name=tool,
        tool_description=description,
        input_schema=schema,
        refusal=refusal,
    )


def _space(*options: FlowToolOption) -> FlowToolOptions:
    return FlowToolOptions(options=list(options), security_classifications_enabled=True)


def _tools(*options: FlowToolOption, over_bound: bool = False):
    listed: SpaceToolOptions = (
        FlowToolOptionsOverBound() if over_bound else _space(*options)
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None, tool_options=listed
    ).tools
    return catalog, render_tool_catalog_block(catalog.projection)


def _schema_of_length(length: int) -> dict[str, object]:
    # Compact sorted JSON of {"a": "x..."} is the value plus 8 characters.
    return {"a": "x" * (length - 8)}


def test_usable_tools_are_offered_by_server_then_tool_and_refused_ones_kept_aside() -> (
    None
):
    # Kills: the reader's order kept (no sort), a refused tool offered as
    # usable, the refused tool dropped instead of recorded with its reason,
    # the description sent uncut, the classification level left out.
    long_description = "Hämtar väderprognos.\n" + "x" * 600
    tools, block = _tools(
        _option("Weather", "forecast", description=long_description, level=2),
        _option(
            "Cases",
            "close_case",
            refusal=UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE,
            description="Stänger ett ärende.",
        ),
        _option("Cases", "lookup_case", description="Slår upp ett ärende."),
    )

    listed = tools.projection
    assert listed.kind == "listed"
    assert listed.omitted_count == 0
    assert [(t.server_name, t.tool_name) for t in listed.tools] == [
        ("Cases", "lookup_case"),
        ("Weather", "forecast"),
    ]
    cut = listed.tools[1].description
    assert len(cut) == RESOURCE_DESCRIPTION_MAX_CHARS
    assert "\n" not in cut and cut.startswith("Hämtar väderprognos. x")
    assert listed.tools[1].classification_level == 2
    assert [(u.server_name, u.tool_name, u.reason) for u in tools.unavailable] == [
        ("Cases", "close_case", UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE)
    ]
    assert block.index('"lookup_case"') < block.index('"forecast"')
    # A refused tool is named with its refusal only, after the usable ones.
    assert block.index('"forecast"') < block.index('"close_case"')
    assert "reason=tool_switched_off_in_space" in block and "Stänger" not in block
    assert "x" * (RESOURCE_DESCRIPTION_MAX_CHARS + 1) not in block


def test_the_overview_budget_lists_a_prefix_and_states_how_many_were_left_out() -> None:
    # Kills: every usable tool listed whatever the budget, omitted tools
    # dropped without a count, the count not stated to the model.
    options = [
        _option("Cases", f"tool_{index:03d}", description="d" * 400)
        for index in reversed(range(120))
    ]
    tools, block = _tools(*options)

    listed = tools.projection
    assert listed.kind == "listed"
    shown = [t.tool_name for t in listed.tools]
    assert 0 < len(shown) < 120
    assert shown == [f"tool_{index:03d}" for index in range(len(shown))]
    assert listed.omitted_count == 120 - len(shown)
    overview = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(overview) == len(shown)
    assert sum(len(line) + 1 for line in overview) <= TOOL_CATALOG_OVERVIEW_MAX_CHARS
    assert f"{listed.omitted_count} more usable" in block


@pytest.mark.parametrize("over_bound", [False, True], ids=["overview", "listing"])
def test_a_catalogue_whose_overview_does_not_fit_is_a_typed_outcome(
    over_bound: bool,
) -> None:
    # Kills: an empty "listed" projection (the model told the space has no
    # tools) when not even one tool fits or the space's list is over the
    # list's bounds; a Builder turn that fails on such a space.
    tools, block = _tools(_option("Cases", "t" * 20_000), over_bound=over_bound)

    assert tools.projection.kind == "too_large"
    assert tools.unavailable == ()
    assert "t" * 100 not in block
    assert "more MCP tools than" in block


def test_an_oversized_tool_hides_only_itself() -> None:
    # Kills: stopping at the first tool that does not fit, so one server's
    # oversized name hides every tool sorted after it.
    tools, block = _tools(
        _option("A", "t" * 7_000), _option("B", "small", description="Litet.")
    )

    listed = tools.projection
    assert listed.kind == "listed"
    assert [t.tool_name for t in listed.tools] == ["small"]
    assert listed.omitted_count == 1
    assert "1 more usable" in block


def test_schemas_share_one_budget_and_an_omitted_one_is_marked() -> None:
    # Kills: each schema compared with the budget alone (no running sum),
    # schemas sent whatever their size, an omitted schema not marked, the
    # first schema over the budget ending the schemas of the tools after it.
    tools, block = _tools(
        _option("Cases", "a", schema=_schema_of_length(5_000)),
        _option("Cases", "b", schema=_schema_of_length(5_000)),
        _option("Cases", "c", schema=_schema_of_length(5_000)),
        _option("Cases", "d", schema=_schema_of_length(1_000)),
        _option("Cases", "e"),
    )

    states = [(t.tool_name, t.schema_state) for t in tools.projection.tools]
    assert states == [
        ("a", "included"),
        ("b", "included"),
        ("c", "over_budget"),
        ("d", "included"),
        ("e", "none_declared"),
    ]
    assert block.count('{"a":"xxx') == 3
    assert "not shown" in block


@pytest.mark.parametrize("excess", [0, 1], ids=["exact_fit", "one_over"])
def test_the_budgets_admit_exactly_their_size(excess: int) -> None:
    # Kills the boundary mutants: `>=` for `>` on either budget and a
    # different newline count in a tool's overview share.
    one_char_name, _ = _tools(_option("S", "n"))
    rendered = render_tool_catalog_block(one_char_name.projection)
    # A tool's share of the overview is its two lines with their newlines.
    name = "n" * (TOOL_CATALOG_OVERVIEW_MAX_CHARS - len(rendered) - 1 + 1 + excess)
    overview, _ = _tools(_option("S", name))
    schema, _ = _tools(
        _option(
            "S", "n", schema=_schema_of_length(TOOL_CATALOG_SCHEMA_MAX_CHARS + excess)
        )
    )

    assert overview.projection.kind == ("listed" if excess == 0 else "too_large")
    assert schema.projection.tools[0].schema_state == (
        "included" if excess == 0 else "over_budget"
    )


def _shape(projection: AIBuilderToolCatalogProjection) -> object:
    if projection.kind != "listed":
        return projection.kind
    return (
        tuple((t.tool_name, t.schema_state) for t in projection.tools),
        projection.omitted_count,
        len(projection.unavailable),
    )


def test_a_catalogue_gives_way_refused_tools_first_then_schemas_then_tools() -> None:
    # Kills: a schema dropped before the refused tools' names, tools dropped
    # before schemas, the first tools dropped instead of the last, the
    # too-large sentence skipped, a block returned that the room does not hold.
    tools, block = _tools(
        _option("S", "a", schema=_schema_of_length(100)),
        _option("S", "b", schema=_schema_of_length(100)),
        _option("S", "c"),
        _option("S", "d", refusal=UnattendedToolRefusal.TOOL_SWITCHED_OFF),
    )
    shapes: list[object] = []
    for room in range(len(block), -1, -1):
        fitted = fit_tool_catalog_projection(
            tools.projection,
            fits=lambda p, room=room: len(render_tool_catalog_block(p)) <= room,
        )
        assert len(render_tool_catalog_block(fitted)) <= room
        if not shapes or shapes[-1] != _shape(fitted):
            shapes.append(_shape(fitted))

    inc, over, none = "included", "over_budget", "none_declared"
    assert shapes == [
        ((("a", inc), ("b", inc), ("c", none)), 0, 1),
        ((("a", inc), ("b", inc), ("c", none)), 0, 0),
        ((("a", inc), ("b", over), ("c", none)), 0, 0),
        ((("a", over), ("b", over), ("c", none)), 0, 0),
        ((("a", over), ("b", over)), 1, 0),
        ((("a", over),), 2, 0),
        "too_large",
        "left_out",
    ]


def test_a_reduction_longer_than_the_one_before_does_not_hide_one_that_fits() -> None:
    # Kills: a search that assumes each reduction is shorter (bisection);
    # here the marker that replaces the empty schema is longer than "{}", so
    # the second reduction does not fit while the first does.
    tools, block = _tools(_option("S", "lookup_" + "abcdefghijklm" * 8, schema={}))

    fitted = fit_tool_catalog_projection(
        tools.projection, fits=lambda p: len(render_tool_catalog_block(p)) <= len(block)
    )

    assert fitted == tools.projection


def _shown(projection: AIBuilderToolCatalogProjection) -> tuple[int, int]:
    if projection.kind != "listed":
        return (0, 0)
    return (
        len(projection.tools),
        sum(t.schema_state == "included" for t in projection.tools),
    )


@pytest.mark.parametrize("window", [6_000, 8_000, 12_000, 128_000])
def test_the_catalogue_takes_only_the_room_a_turn_without_tools_leaves(
    window: int,
) -> None:
    # Kills: the catalogue measured as required prompt content (a small
    # window refuses the proposal or the answer reserve shrinks), no
    # fitting to the model's room, a fitted catalogue not recorded on the
    # turn, a large window shown less than the whole projection.
    # Ordinary text, not repeated characters, so that tokens are counted as
    # they would be for a real catalogue.
    schema = {
        "type": "object",
        "properties": {
            f"field_{i}": {"type": "string", "description": "Datum ÅÅÅÅ-MM-DD."}
            for i in range(10)
        },
    }
    space = _space(
        *(
            _option(
                "Cases",
                f"tool_{i:02d}",
                description="Hämtar ärenden för uppföljning och analys. " * 6,
                schema=schema,
            )
            for i in range(19)
        )
    )

    # One conversation for both turns: a showing's token differs per showing.
    conversation = conversation_using_tools({})

    def prepare(tool_options: SpaceToolOptions | None):
        return build_proposal_prepared(
            requirements_state=RequirementsState(),
            ui_language="en",
            slot_classification_metadata=None,
            conversation=conversation,
            planning_state=_document_architecture_state(),
            attachment_context=None,
            flow_context=None,
            is_edit_mode=False,
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[], available_kbs=[], tool_options=tool_options
            ),
            flow=None,
            assistant_snapshots=None,
            plan_edit_context=None,
            prior_plan_for_revision=None,
            litellm_model="openai/gpt-5.4",
            capacity=ModelCapacity(window, 4_096),
            budget_policy=_budget_policy(),
            attachment_file_count=0,
            current_turn_start=0,
        )

    without, with_tools = prepare(None), prepare(space)
    full, _ = _tools(*space.options)

    assert isinstance(without.request_budget, AIBuilderPlannedRequestBudget)
    assert isinstance(with_tools.request_budget, AIBuilderPlannedRequestBudget)
    # Only the schema's tool_use property is required content; the
    # catalogue's text is not.
    assert (
        with_tools.request_budget.required_input_tokens
        - without.request_budget.required_input_tokens
        == _schema_tokens(full.listed_refs) - _schema_tokens(())
    )
    fitted = with_tools.resource_catalog.tools.projection
    prompt = str(with_tools.llm_messages[0]["content"])
    if window == 128_000:
        assert fitted == full.projection
    else:
        assert _shown(fitted) < _shown(full.projection)
    assert render_tool_catalog_block(fitted) in prompt
    # A step names only a tool the prompt shows.
    step = with_tools.proposal_tool_schema["function"]["parameters"]["properties"][
        "steps"
    ]["items"]["properties"]
    offered = (
        step["tool_use"]["properties"]["tool_ref"]["enum"] if "tool_use" in step else []
    )
    assert offered == list(with_tools.resource_catalog.tools.listed_refs)


def _schema_tokens(tool_refs: tuple[str, ...]) -> int:
    schema = build_propose_flow_tool_schema(
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
        tool_refs=tool_refs,
    )
    return count_tool_tokens(
        outbound_proposal_tool_schemas(
            proposal_turn_tool_schemas(schema, None), strict=False
        ),
        "openai/gpt-5.4",
    )


def test_a_space_without_tools_adds_nothing_to_the_prompt() -> None:
    # Kills: a tools heading or sentence rendered for a space with no tools.
    tools, block = _tools()

    assert tools.projection.kind == "listed"
    assert tools.projection.tools == () and tools.unavailable == ()
    assert block == ""
