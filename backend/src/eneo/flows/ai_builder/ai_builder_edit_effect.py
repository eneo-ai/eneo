"""What an edit changed: the observed effect of a final spec on the saved one.

Steps are compared by identity, never by position: a saved step is its
`existing_step_ref` in both specs, a step the edit adds is its plan ref. The
effect is a set of typed facts plus the survivors' order; it says nothing of
what was asked for. Display values are not effects; the preview keeps them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    build_form_field_changes,
    build_step_changes,
)
from eneo.flows.ai_builder.ai_builder_edit_preview_models import StepChangeField
from eneo.flows.ai_builder.ai_builder_step_reads import (
    ReadChannel,
    ReadSite,
    StepRead,
    spec_step_refs,
    step_reads,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.input_binding_contract_rules import SourceRefBinding


@dataclass(frozen=True, slots=True)
class FieldEffect:
    identity: str
    field: StepChangeField


@dataclass(frozen=True, slots=True)
class StructureEffect:
    change: Literal["added", "removed"]
    identity: str


@dataclass(frozen=True, slots=True)
class FormEffect:
    change: Literal["added", "removed", "modified"]
    name: str


@dataclass(frozen=True, slots=True)
class FlowPropertyEffect:
    name: Literal["flow_name", "flow_description"]


@dataclass(frozen=True, slots=True)
class DocumentBodyWriterEffect:
    """A step became, or stopped being, a document body writer: the spec names
    it, not its fields, and document topology and checkpoints read it."""

    change: Literal["added", "removed"]
    identity: str


@dataclass(frozen=True, slots=True)
class ReadKey:
    """One read by what is read and where. `producer` is the identity of the
    step read, None for a read of no step (a form field, the run input)."""

    producer: str | None
    channel: ReadChannel
    path: tuple[str, ...]
    site: ReadSite
    label: str | None = None
    item_template: str | None = None


@dataclass(frozen=True, slots=True)
class ReadEffect:
    consumer: str
    change: Literal["added", "removed"]
    read: ReadKey


@dataclass(frozen=True, slots=True)
class OrderEffect:
    """The surviving saved steps, in saved and in final order."""

    saved: tuple[str, ...]
    final: tuple[str, ...]


Effect = (
    FieldEffect
    | StructureEffect
    | FormEffect
    | FlowPropertyEffect
    | DocumentBodyWriterEffect
    | ReadEffect
)


@dataclass(frozen=True, slots=True)
class EditEffect:
    effects: frozenset[Effect]
    # None when every surviving saved step keeps its relative order.
    order: OrderEffect | None


def edit_effect(saved: FlowDraftSpecCore, final: FlowDraftSpecCore) -> EditEffect:
    """Every observed difference between `saved` and `final`, by step identity.

    Step fields and form fields are compared as the preview diff compares
    them (its step references made identities first). Reads come from
    `step_reads` on each spec, their producer positions mapped through that
    spec's own identities: a read that follows its producer through a reorder
    is no effect, and a read redirected to another step is one removed and one
    added read. A step's reads are its effects whether it survives, is added
    or is removed. The document body writers are compared by identity too.
    """

    saved_ids, final_ids = _identities(saved), _identities(final)
    effects: set[Effect] = {
        FieldEffect(change.step_ref, field_change.field)
        for change in build_step_changes(
            base_spec=saved, compiled_steps=final.steps, removed_refs=frozenset()
        )
        if change.step_ref is not None
        for field_change in change.field_changes
    }
    effects.update(StructureEffect("added", i) for i in final_ids if i not in saved_ids)
    effects.update(
        StructureEffect("removed", i) for i in saved_ids if i not in final_ids
    )
    effects.update(
        FormEffect(change.kind, change.field_name)
        for change in build_form_field_changes(saved.form_fields, final.form_fields)
    )
    if saved.flow_name != final.flow_name:
        effects.add(FlowPropertyEffect("flow_name"))
    if saved.flow_description != final.flow_description:
        effects.add(FlowPropertyEffect("flow_description"))
    saved_writers = _body_writers(saved, saved_ids)
    final_writers = _body_writers(final, final_ids)
    effects.update(
        DocumentBodyWriterEffect("removed", i) for i in saved_writers - final_writers
    )
    effects.update(
        DocumentBodyWriterEffect("added", i) for i in final_writers - saved_writers
    )
    saved_reads, final_reads = _reads(saved, saved_ids), _reads(final, final_ids)
    for consumer in saved_reads.keys() | final_reads.keys():
        before = saved_reads.get(consumer, frozenset())
        after = final_reads.get(consumer, frozenset())
        effects.update(ReadEffect(consumer, "removed", key) for key in before - after)
        effects.update(ReadEffect(consumer, "added", key) for key in after - before)
    order = OrderEffect(
        saved=tuple(i for i in saved_ids if i in final_ids),
        final=tuple(i for i in final_ids if i in saved_ids),
    )
    return EditEffect(frozenset(effects), order if order.saved != order.final else None)


def order_matches_moves(order: OrderEffect | None, moved: frozenset[str]) -> bool:
    """Whether the declared moves explain the order: every survivor outside
    `moved` keeps its saved relative order, and every step in `moved` has
    other saved steps before it than it had."""

    saved, final = (order.saved, order.final) if order is not None else ((), ())
    unmoved = [i for i in saved if i not in moved]
    return unmoved == [i for i in final if i not in moved] and all(
        ref in final and _before(saved, ref) != _before(final, ref) for ref in moved
    )


def _identities(spec: FlowDraftSpecCore) -> tuple[str, ...]:
    return tuple(step.existing_step_ref or step.plan_step_ref for step in spec.steps)


def _body_writers(
    spec: FlowDraftSpecCore, identities: tuple[str, ...]
) -> frozenset[str]:
    refs = set(spec.document_body_writer_step_refs or ())
    return frozenset(
        identity
        for identity, step in zip(identities, spec.steps, strict=True)
        if step.plan_step_ref in refs
    )


def _before(sequence: tuple[str, ...], identity: str) -> frozenset[str]:
    return frozenset(sequence[: sequence.index(identity)])


def _reads(
    spec: FlowDraftSpecCore, identities: tuple[str, ...]
) -> dict[str, frozenset[ReadKey]]:
    step_refs = spec_step_refs(spec.steps)
    forms = {field.name for field in spec.form_fields or []}
    # A position outside the spec names no step.
    by_order: dict[int | None, str] = dict(enumerate(identities, 1))
    return {
        identity: frozenset(
            _read_key(read, by_order.get(read.producer_order))
            for read in step_reads(
                step, order=order, step_refs=step_refs, form_field_names=forms
            )
        )
        for order, (identity, step) in enumerate(
            zip(identities, spec.steps, strict=True), 1
        )
    }


def _read_key(read: StepRead, producer: str | None) -> ReadKey:
    ref = read.origin if isinstance(read.origin, SourceRefBinding) else None
    return ReadKey(
        producer,
        read.channel,
        read.path,
        read.site,
        ref.label if ref is not None else None,
        ref.item_template if ref is not None else None,
    )
