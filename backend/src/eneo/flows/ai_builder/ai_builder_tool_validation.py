"""What the AI Builder does with a tool step a turn writes.

Three outcomes, never a guessed tool: a tool use whose ref names no tool is
repaired by the model; a tool the space may not use, or whose input schema no
flow can check, is the person's to change, so the turn answers with why
(``ProposalAnswer``); an argument the tool's input schema refuses is repaired
by the model. The argument checks are publish's own
(``check_tool_configuration``), run on the final compiled spec, so a tool
step the Builder proposes is one publish accepts. When publish's checker of
fixed values fails on the host, nothing is proven: the plan carries a warning.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from typing import Final

from eneo.flows.ai_builder.ai_builder_domain_models import LintSeverity
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    non_plan_outcome,
    uses_english,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    BoundedListing,
    CorrectableFailure,
    ProposalAnswer,
    display_value,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import AIBuilderToolCatalog
from eneo.flows.ai_builder.ai_builder_tool_use import (
    ARGUMENT_SCHEMA_FEEDBACK_MAX_CHARS,
    ToolUseIntent,
    ToolUseRefUnavailable,
    ToolUseRefUnknown,
    argument_schema,
    bind_tool_use,
    declared_arguments_text,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.application.flow_tool_options import FlowToolOption
from eneo.flows.application.flow_tool_publication import (
    REFUSAL_SENTENCES,
    ToolConfigurationProblem,
    check_tool_configuration,
)
from eneo.flows.domain.tool_input import read_tool_input_config
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, InputSource, StepSpec
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal

_REFUSAL_SENTENCES_SV: Final[Mapping[UnattendedToolRefusal, str]] = {
    UnattendedToolRefusal.SERVER_NOT_FOUND: (
        "verktygets MCP-server finns inte längre, så välj ett annat verktyg."
    ),
    UnattendedToolRefusal.SERVER_DISABLED: (
        "verktygets MCP-server är avstängd, vilket instansens administratör kan ändra."
    ),
    UnattendedToolRefusal.SERVER_NOT_GENERAL: (
        "verktyget hör till en inbyggd funktion som ett flöde inte kan anropa "
        "som verktyg, så välj ett annat verktyg."
    ),
    UnattendedToolRefusal.SERVER_FORWARDS_IDENTITY: (
        "verktygets MCP-server svarar som den inloggade användaren och en "
        "flödeskörning har ingen, vilket instansens administratör kan ändra på "
        "servern."
    ),
    UnattendedToolRefusal.TOOL_NOT_FOUND: (
        "verktyget finns inte längre på sin MCP-server, så välj ett annat verktyg."
    ),
    UnattendedToolRefusal.TOOL_REMOVED_AT_SERVER: (
        "MCP-servern erbjuder inte längre verktyget, så välj ett annat verktyg."
    ),
    UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW: (
        "verktyget är nytt eller har ändrats på sin MCP-server och väntar på en "
        "granskning, som instansens administratör gör."
    ),
    UnattendedToolRefusal.TOOL_SWITCHED_OFF: (
        "verktyget är avstängt, vilket instansens administratör kan ändra."
    ),
    UnattendedToolRefusal.SPACE_IS_PERSONAL: (
        "ett flöde i en personlig yta kan inte använda verktyg, så bygg flödet i "
        "en delad yta."
    ),
    UnattendedToolRefusal.SERVER_NOT_IN_SPACE: (
        "verktygets MCP-server är inte tillagd i den här ytan, vilket en "
        "administratör för ytan kan ändra."
    ),
    UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE: (
        "verktyget är avstängt i den här ytan, vilket en administratör för ytan "
        "kan ändra."
    ),
    UnattendedToolRefusal.SERVER_BELOW_SPACE_CLASSIFICATION: (
        "verktygets MCP-server har en lägre säkerhetsklassning än den här ytan, "
        "vilket en administratör för ytan kan ändra för ytan eller instansens "
        "administratör för servern."
    ),
}

_INVALID_SCHEMA_SENTENCES: Final[Mapping[str, str]] = {
    "sv": (
        "MCP-serverns indataschema för verktyget är inget giltigt JSON Schema av "
        "en version som Eneo stöder, så ett flöde kan inte kontrollera "
        "verktygets argument. Schemat rättas på servern."
    ),
    "en": (
        "the input schema the MCP server gives for the tool is not a valid JSON "
        "Schema of a draft Eneo supports, so a flow cannot check the tool's "
        "arguments. The schema is the server's to correct."
    ),
}


def tool_use_ref_outcome(
    uses: Iterable[tuple[str, ToolUseIntent]],
    *,
    catalog: AIBuilderToolCatalog,
    ui_language: str | None,
) -> CorrectableFailure | ProposalAnswer | None:
    """The turn's answer for tool uses, labelled by step, whose ref names no
    tool the step may read; None when every ref names a usable tool.

    Run before compile, in create and edit alike. A refused tool ends the
    turn with why, for the first such use: no other tool takes its place.
    """
    unknown = BoundedListing()
    for label, use in uses:
        binding = bind_tool_use(use, catalog)
        if isinstance(binding, ToolUseRefUnavailable):
            return _tool_not_usable_answer(
                binding.tool_name,
                binding.server_name,
                reason=binding.reason,
                ui_language=ui_language,
            )
        if isinstance(binding, ToolUseRefUnknown):
            unknown.add(partial(_unknown_ref_line, label, binding.tool_ref))
    if not unknown.total:
        return None
    valid = BoundedListing()
    for ref in catalog.listed_refs:
        valid.add(partial(display_value, ref))
    return CorrectableFailure(
        feedback="\n".join(
            (
                unknown.render("Replace these tool refs with a listed tool's ref:"),
                valid.render(f"Listed tool refs ({valid.total}):"),
            )
        ),
        kind="validation",
        codes=frozenset({"unknown_tool_ref"}),
        producers=frozenset({"platform_validator"}),
    )


async def check_written_tool_steps(
    spec: FlowDraftSpecCore,
    *,
    written: Callable[[StepSpec], bool],
    catalog: AIBuilderToolCatalog,
    validation: SpecValidationResult,
    ui_language: str | None,
) -> ProposalAnswer | None:
    """Publish's checks of every tool step of the final spec the turn wrote
    (``written``; a saved step kept as it is was published before): an
    argument the tool's input schema refuses is an error the model repairs,
    an unverified fixed value a warning, and a schema no flow can check the
    answer the turn ends with."""
    for step in spec.steps:
        if step.input_source is not InputSource.TOOL or not written(step):
            continue
        config = read_tool_input_config(step.input_config)
        tool = catalog.usable_option(config.mcp_server_id, config.tool_id)
        if tool is None:
            raise ValueError(
                f"Step {step.plan_step_ref} was written with a tool the turn's "
                "catalogue does not offer."
            )
        finding = await check_tool_configuration(config, input_schema=tool.input_schema)
        if finding is None:
            continue
        if finding.problem is ToolConfigurationProblem.INVALID_SCHEMA:
            return _tool_not_usable_answer(
                tool.tool_name,
                tool.mcp_server_name,
                reason=None,
                ui_language=ui_language,
            )
        if finding.problem is ToolConfigurationProblem.UNVERIFIED:
            validation.add_warning(
                step_ref=step.plan_step_ref,
                code="tool_argument_unverified",
                message=(
                    f"Step '{display_value(step.name)}': the fixed arguments of "
                    f"tool '{display_value(tool.tool_name)}' could not be checked "
                    "against its input schema now; publishing checks them again."
                ),
                severity=LintSeverity.WARNING,
            )
            continue
        argument = finding.argument or ""
        if finding.problem is ToolConfigurationProblem.MISSING_REQUIRED:
            problem = (
                "its input_schema requires it; give it a fixed value, a run-form "
                "field or an earlier step's field."
            ) + _argument_schema_hint(tool, argument)
        elif finding.problem is ToolConfigurationProblem.UNDECLARED_ARGUMENT:
            problem = (
                "its input_schema declares no such argument and takes no other; "
                "its declared arguments are: "
                f"{display_value(declared_arguments_text(tool))}."
            )
        else:
            problem = (
                "the fixed value does not fit its input_schema"
                + ("" if finding.rule is None else f" (rule '{finding.rule}')")
                + "."
                + _argument_schema_hint(tool, argument)
            )
        validation.add_error(
            step_ref=step.plan_step_ref,
            code=f"tool_argument_{finding.problem.value}",
            message=(
                f"Step '{display_value(step.name)}', tool "
                f"'{display_value(tool.tool_name)}', argument "
                f"'{display_value(argument)}': {problem}"
            ),
        )
    return None


def _argument_schema_hint(tool: FlowToolOption, argument: str) -> str:
    schema = argument_schema(tool, argument)
    if schema is None:
        return ""
    text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(text) > ARGUMENT_SCHEMA_FEEDBACK_MAX_CHARS:
        return ""
    return f" The argument's schema: {text}"


def _unknown_ref_line(label: str, ref: str) -> str:
    return f"Unknown tool ref '{display_value(ref)}' at {label}."


def _tool_not_usable_answer(
    tool_name: str,
    server_name: str,
    *,
    reason: UnattendedToolRefusal | None,
    ui_language: str | None,
) -> ProposalAnswer:
    english = uses_english(ui_language)
    language = "en" if english else "sv"
    if reason is None:
        why = _INVALID_SCHEMA_SENTENCES[language]
    elif english:
        sentence = REFUSAL_SENTENCES[reason]
        why = sentence[0].lower() + sentence[1:]
    else:
        why = _REFUSAL_SENTENCES_SV[reason]
    tool, server = display_value(tool_name), display_value(server_name)
    answer = (
        f"I can't build a step that uses the tool `{tool}` on the MCP server "
        f"`{server}`: {why}"
        if english
        else f"Jag kan inte bygga ett steg som använder verktyget `{tool}` på "
        f"MCP-servern `{server}`: {why}"
    )
    return ProposalAnswer(
        answer=answer,
        outcome=non_plan_outcome(
            "tool_not_usable", "make_tool_usable", affected=(tool_name,)
        ),
        codes=frozenset({"tool_invalid_schema" if reason is None else reason.value}),
    )
