"""The editor updates that fix a suggestion, as plain JSON.

Each builder returns the body of an editor update without
``expected_revision`` (``definition``, ``step_edits``, ``assistants``,
``step_order``, whichever the fix needs), or None when the fix is not
mechanical. A builder that rewrites reads checks, with ``step_lineage``, that
the step reads afterwards exactly what it read less what the fix removes, so
a patch never changes a read it does not name. The application validates the
body against the editor update and the publish rules before it offers it.

Steps and assistants are named by id. An assistant change names its step
(``step_id``), so an assistant other steps share is copied for the step, not
changed for them. Columns a patch writes are written as the steps will be
numbered after it; the editor update renumbers the reads of every column and
prompt it does not write.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    SuggestionStep,
    exact_expression,
    step_reads,
)
from eneo.flows.enums import FlowInputSource, FlowOutputType
from eneo.flows.flow_authoring_variable_rewriting import (
    rewrite_step_alias_heads,
    rewrite_template_expressions,
)
from eneo.flows.flow_variable_definitions import PREVIOUS_STEP_TEXT_ALIAS
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    has_explicit_underlag,
    question_binding,
    source_ref_step_order,
)
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    PROMPT_READ_SITE_PREFIX,
    STRUCTURED_SELECTOR_HEAD,
    StepRead,
    build_step_ref_mapping,
)
from eneo.flows.variable_resolver import runtime_step_alias, runtime_step_alias_order

_SOURCE_REF_SITE_PREFIX = "input_bindings.source_refs["
_QUESTION_SITE = "input_bindings.question"

ReadKey = tuple[str, int, tuple[str, ...]]


def editor_patch(
    *,
    definition: Mapping[str, object] | None = None,
    step_edits: Sequence[Mapping[str, object]] = (),
    assistants: Sequence[Mapping[str, object]] = (),
    step_order: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """An editor update body; ``definition`` is required by the update, so an
    empty one stands for "the definition as saved"."""
    patch: dict[str, Any] = {"definition": dict(definition or {})}
    if step_edits:
        patch["step_edits"] = [dict(edit) for edit in step_edits]
    if assistants:
        patch["assistants"] = [dict(change) for change in assistants]
    if step_order is not None:
        patch["step_order"] = [dict(slot) for slot in step_order]
    return patch


def _bindings_edit(
    step: SuggestionStep, bindings: Mapping[str, object] | None
) -> dict[str, object]:
    return {
        "step_id": str(step.id),
        "changes": {"input_bindings": dict(bindings) if bindings else None},
    }


def _prompt_change(step: SuggestionStep, text: str) -> dict[str, object]:
    return {
        "assistant_id": str(step.assistant_id),
        "step_id": str(step.id),
        "changes": {"prompt": {"text": text, "description": step.prompt_description}},
    }


def _read_key(read: StepRead) -> ReadKey:
    return (read.channel, read.step_order, read.selector)


# --------------------------------------------------------------------------- #
# duplicate_read: remove the redundant reads
# --------------------------------------------------------------------------- #


def remove_reads_patch(
    step: SuggestionStep,
    redundant: Sequence[StepRead],
    *,
    step_ref_mapping: dict[str, int],
) -> dict[str, Any] | None:
    """Remove ``redundant`` from ``step``: a prompt read standing on its own
    line (that line goes, and one blank line it leaves next to another), a
    question that is exactly the read, a source ref. None when a read is
    written another way, or when removing it would change anything else the
    step reads: a step whose underlag would go empty reads its
    ``input_source`` instead, which is more than the duplicate."""

    prompt = step.prompt_text
    bindings: dict[str, Any] | None = (
        copy.deepcopy(dict(step.input_bindings)) if step.input_bindings else None
    )
    removed_refs: set[int] = set()
    for read in redundant:
        if read.site.startswith(PROMPT_READ_SITE_PREFIX):
            if prompt is None:
                return None
            prompt = prompt_without_line(
                prompt, read.site.removeprefix(PROMPT_READ_SITE_PREFIX)
            )
            if prompt is None:
                return None
        elif read.site == _QUESTION_SITE:
            question = question_binding(bindings)
            if (
                bindings is None
                or question is None
                or exact_expression(question) is None
            ):
                return None
            bindings.pop("question")
        elif read.site.startswith(_SOURCE_REF_SITE_PREFIX):
            removed_refs.add(int(read.site.removeprefix(_SOURCE_REF_SITE_PREFIX)[:-1]))
        else:
            return None
    if removed_refs and bindings is not None:
        refs = cast(list[Any], bindings.get(SOURCE_REFS_BINDING_KEY) or [])
        kept = [ref for index, ref in enumerate(refs) if index not in removed_refs]
        if kept:
            bindings[SOURCE_REFS_BINDING_KEY] = kept
        else:
            bindings.pop(SOURCE_REFS_BINDING_KEY, None)
    new_bindings = bindings or None
    if has_explicit_underlag(step.input_bindings) and not has_explicit_underlag(
        new_bindings
    ):
        return None
    patched = replace(step, input_bindings=new_bindings, prompt_text=prompt)
    expected = list(map(_read_key, step_reads(step, step_ref_mapping)))
    for read in redundant:
        expected.remove(_read_key(read))
    if sorted(map(_read_key, step_reads(patched, step_ref_mapping))) != sorted(
        expected
    ):
        return None
    return editor_patch(
        step_edits=(
            [_bindings_edit(step, new_bindings)]
            if new_bindings != (step.input_bindings or None)
            else []
        ),
        assistants=(
            [_prompt_change(step, prompt)]
            if prompt is not None and prompt != step.prompt_text
            else []
        ),
    )


def prompt_without_line(prompt: str, expression: str) -> str | None:
    """``prompt`` without the last line that is exactly ``{{ expression }}``,
    None when no line is. A blank line the removal leaves next to another
    blank line, or at the start or end of the prompt, goes with it."""

    lines = prompt.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if exact_expression(line) == expression
    ]
    if not matches:
        return None
    index = matches[-1]
    removed = lines.pop(index)

    def blank(at: int) -> bool:
        return 0 <= at < len(lines) and not lines[at].strip()

    has_prev, has_next = index > 0, index < len(lines)
    if blank(index) and (blank(index - 1) or not has_prev):
        lines.pop(index)
    elif blank(index - 1) and not has_next:
        lines.pop(index - 1)
    text = "".join(lines)
    if not removed.endswith(("\n", "\r")):
        # The removed line was the last one, without a line break: so is the
        # line that now ends the prompt.
        for ending in ("\r\n", "\n", "\r"):
            if text.endswith(ending):
                text = text[: -len(ending)]
                break
    return text


# --------------------------------------------------------------------------- #
# unread_contract_fields, unread_result, unused_form_field
# --------------------------------------------------------------------------- #


def contract_without_fields_patch(
    step: SuggestionStep, fields: Iterable[str]
) -> dict[str, Any] | None:
    """The step's output contract without the top-level ``fields``, in its
    ``properties`` and its ``required``."""

    contract = step.output_contract
    if contract is None or not isinstance(contract.get("properties"), Mapping):
        return None
    dropped = set(fields)
    narrowed: dict[str, Any] = copy.deepcopy(dict(contract))
    narrowed["properties"] = {
        name: value
        for name, value in cast(Mapping[str, Any], contract["properties"]).items()
        if name not in dropped
    }
    required = contract.get("required")
    if isinstance(required, list):
        narrowed["required"] = [
            name for name in cast(list[Any], required) if name not in dropped
        ]
    return editor_patch(
        step_edits=[{"step_id": str(step.id), "changes": {"output_contract": narrowed}}]
    )


def remove_step_patch(
    steps: Sequence[SuggestionStep], removed: SuggestionStep
) -> dict[str, Any]:
    """The editor update that removes ``removed``: the step order without it."""
    return editor_patch(
        step_order=[
            {"step_id": str(step.id)}
            for step in sorted(steps, key=lambda item: item.step_order)
            if step.id != removed.id
        ]
    )


def form_without_field_patch(
    metadata_json: Mapping[str, object], field: str
) -> dict[str, Any] | None:
    """The saved metadata with the run form field ``field`` removed, the rest
    copied as it is."""

    metadata: dict[str, Any] = copy.deepcopy(dict(metadata_json))
    form_schema = metadata.get("form_schema")
    if not isinstance(form_schema, dict):
        return None
    fields = cast(dict[str, Any], form_schema).get("fields")
    if not isinstance(fields, list):
        return None
    saved = cast(list[Any], fields)
    kept: list[Any] = [item for item in saved if _field_name(item) != field]
    if len(kept) == len(saved):
        return None
    form_schema["fields"] = kept
    return editor_patch(definition={"metadata_json": metadata})


def _field_name(item: object) -> str | None:
    if not isinstance(item, Mapping):
        return None
    name = cast(Mapping[str, object], item).get("name")
    return name.strip() if isinstance(name, str) else None


# --------------------------------------------------------------------------- #
# relay_step: readers read the source, the relay goes
# --------------------------------------------------------------------------- #


def relay_patch(
    draft: DraftReads, relay: SuggestionStep, source_order: int
) -> dict[str, Any] | None:
    """Every later read of ``relay`` rewritten to read the step at
    ``source_order`` (what the relay copies), and the relay removed, in one
    editor update. None when a read cannot be rewritten mechanically: a read
    in a step's configuration, a path the source does not declare, a reader
    whose ``previous_step`` would come to read another step, or any other
    read of the relay's result than its text or structured value."""

    relay_order = relay.step_order
    source = draft.step_at(source_order)
    if source is None or not source_order < relay_order:
        return None

    def renumbered(order: int) -> int:
        if order == relay_order:
            return source_order
        return order - 1 if order > relay_order else order

    after = build_step_ref_mapping(
        {
            "step_order": renumbered(step.step_order),
            "user_description": step.user_description,
        }
        for step in draft.steps
        if step.step_order != relay_order
    )
    step_edits: list[dict[str, object]] = []
    assistants: list[dict[str, object]] = []
    for reader in draft.steps:
        if reader.step_order <= relay_order:
            continue
        reads = [
            read
            for read in draft.reads[reader.step_order]
            if read.step_order == relay_order
        ]
        if not reads:
            continue
        for read in reads:
            if read.channel == "config" or not _source_has(source, read.selector):
                return None
            if (
                read.site == INPUT_SOURCE_READ_SITE
                and FlowInputSource(reader.input_source)
                is FlowInputSource.PREVIOUS_STEP
                and source_order != relay_order - 1
            ):
                return None

        def rewrite(text: str, reader: SuggestionStep = reader) -> str:
            return _relay_template(
                text,
                reader_order=reader.step_order,
                relay_order=relay_order,
                source_order=source_order,
                step_ref_mapping=draft.step_ref_mapping,
                renumbered=renumbered,
            )

        # Every column and prompt as it reads after the change: those that
        # read the relay are written so, the others the editor update
        # renumbers the same way.
        bindings = _relay_bindings(
            reader.input_bindings,
            rewrite=rewrite,
            relay_order=relay_order,
            step_ref_mapping=draft.step_ref_mapping,
            renumbered=renumbered,
        )
        prompt = rewrite(reader.prompt_text) if reader.prompt_text else None
        # Only the columns and prompts that read the relay are written, and
        # only when the rewrite changes them (``föregående_steg`` after a
        # relay of the step before it already names the source).
        sites = {read.site for read in reads}
        if any(site.startswith("input_bindings.") for site in sites) and (
            bindings != (reader.input_bindings or None)
        ):
            step_edits.append(_bindings_edit(reader, bindings))
        if (
            prompt is not None
            and prompt != reader.prompt_text
            and any(site.startswith(PROMPT_READ_SITE_PREFIX) for site in sites)
        ):
            assistants.append(_prompt_change(reader, prompt))
        # The reader, renumbered, reads what it read with the relay read as
        # its source. The configuration channel, which the update renumbers,
        # holds no read of the relay (checked above).
        expected = {
            (read.channel, renumbered(read.step_order), read.selector)
            for read in draft.reads[reader.step_order]
            if read.channel != "config"
        }
        moved = replace(
            reader,
            step_order=renumbered(reader.step_order),
            input_bindings=bindings,
            prompt_text=prompt,
        )
        if {
            _read_key(read)
            for read in step_reads(moved, after)
            if read.channel != "config"
        } != expected:
            return None
    return editor_patch(
        step_edits=step_edits,
        assistants=assistants,
        step_order=[
            {"step_id": str(step.id)}
            for step in draft.steps
            if step.step_order != relay_order
        ],
    )


def _source_has(source: SuggestionStep, selector: tuple[str, ...]) -> bool:
    """Whether the source carries what a reader reads of the relay: its text
    always, its structured value or a path in it when it is a JSON step whose
    contract declares the path."""
    if selector == ():
        return True
    if selector[:1] != (STRUCTURED_SELECTOR_HEAD,):
        return False
    if FlowOutputType(source.output_type) is not FlowOutputType.JSON:
        return False
    return contract_declares_path(source.output_contract, selector[1:])


def contract_declares_path(
    contract: Mapping[str, object] | None, path: Sequence[str]
) -> bool:
    """Whether ``contract`` declares the object path ``path`` (each segment
    a key of ``properties``; an array's items under a numeric segment)."""
    node: Mapping[str, object] | None = contract
    for segment in path:
        if node is None:
            return False
        items = node.get("items")
        if segment.isdigit() and isinstance(items, Mapping):
            node = cast(Mapping[str, object], items)
            continue
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            return False
        child = cast(Mapping[str, object], properties).get(segment)
        node = cast(Mapping[str, object], child) if isinstance(child, Mapping) else None
        if child is None:
            return False
    return contract is not None


def _relay_template(
    text: str,
    *,
    reader_order: int,
    relay_order: int,
    source_order: int,
    step_ref_mapping: Mapping[str, int],
    renumbered: Callable[[int], int],
) -> str:
    """``text`` as it reads after the relay goes: a read of the relay by name
    or as ``föregående_steg`` reads the source by its alias, and every alias
    is renumbered (the relay's to the source's)."""

    source_alias = runtime_step_alias(source_order)

    def by_name(expression: str) -> str | None:
        segments = expression.split(".")
        head = segments[0].strip()
        if (
            runtime_step_alias_order(head) is None
            and step_ref_mapping.get(head) == relay_order
        ):
            leading = segments[0][: len(segments[0]) - len(segments[0].lstrip())]
            trailing = segments[0][len(segments[0].rstrip()) :]
            return ".".join([f"{leading}{source_alias}{trailing}", *segments[1:]])
        if (
            expression.strip() == PREVIOUS_STEP_TEXT_ALIAS
            and reader_order == relay_order + 1
            and source_order != relay_order - 1
        ):
            return source_alias
        return None

    text = rewrite_template_expressions(text, by_name)
    return rewrite_step_alias_heads(
        text,
        lambda order, _: (
            runtime_step_alias(renumbered(order))
            if renumbered(order) != order
            else None
        ),
    )


def _relay_bindings(
    bindings: Mapping[str, object] | None,
    *,
    rewrite: Callable[[str], str],
    relay_order: int,
    step_ref_mapping: Mapping[str, int],
    renumbered: Callable[[int], int],
) -> dict[str, Any] | None:
    """The reader's underlag with its templates rewritten and the
    ``step_ref`` of each source ref naming the step it reads after the relay
    goes."""
    if not bindings:
        return None
    rewritten = cast(dict[str, Any], _rewrite_strings(dict(bindings), rewrite))
    refs = rewritten.get(SOURCE_REFS_BINDING_KEY)
    if isinstance(refs, list):
        rewritten[SOURCE_REFS_BINDING_KEY] = [
            _relay_source_ref(
                ref,
                relay_order=relay_order,
                step_ref_mapping=step_ref_mapping,
                renumbered=renumbered,
            )
            for ref in cast(list[Any], refs)
        ]
    return rewritten


def _relay_source_ref(
    ref: Any,
    *,
    relay_order: int,
    step_ref_mapping: Mapping[str, int],
    renumbered: Callable[[int], int],
) -> Any:
    if not isinstance(ref, dict):
        return ref
    payload = cast(dict[str, Any], ref)
    step_ref = payload.get("step_ref")
    if not isinstance(step_ref, str):
        return payload
    order = source_ref_step_order(step_ref)
    if order is None and step_ref_mapping.get(step_ref.strip()) == relay_order:
        order = relay_order
    if order is None or renumbered(order) == order:
        return payload
    return {**payload, "step_ref": runtime_step_alias(renumbered(order))}


def _rewrite_strings(value: Any, rewrite: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return rewrite(value)
    if isinstance(value, dict):
        return {
            key: _rewrite_strings(inner, rewrite)
            for key, inner in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [_rewrite_strings(item, rewrite) for item in cast(list[Any], value)]
    return value


__all__ = [
    "contract_declares_path",
    "contract_without_fields_patch",
    "editor_patch",
    "form_without_field_patch",
    "prompt_without_line",
    "relay_patch",
    "remove_reads_patch",
    "remove_step_patch",
]
