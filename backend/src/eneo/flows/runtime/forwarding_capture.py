"""Attempt-scoped capture of what a model call forwards, for its forwarding facts.

The executor opens one capture per step attempt. While it is open:

- every value an input edge is built from is held by reference, keyed by the
  edge's hash (``flow_run_provenance.observe_selected_values``);
- activation hands over the attempt's resolved input edges, so a call's edge
  indexes resolve to their values;
- the first model call that returns output is measured
  (``forwarding_facts.measure_forwarding_facts``), and later calls are only
  counted.

The held values live in memory only, for the attempt's duration: they are never
persisted, logged or put in evidence. What leaves the capture is the
``ForwardingFacts`` of numbers and edge indexes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.forwarding_facts import ForwardingFacts
from eneo.flows.domain.step_output import FlowResolvedInputHashedSelection
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    observe_selected_values,
)
from eneo.flows.runtime.forwarding_facts import (
    Clock,
    ForwardingSegment,
    measure_forwarding_facts,
)

logger = logging.getLogger(__name__)

_SelectionKey = tuple[str, str]


def _empty_values() -> dict[_SelectionKey, object]:
    return {}


@dataclass(slots=True)
class ForwardingCapture:
    clock: Clock | None = None
    _values: dict[_SelectionKey, object] = field(default_factory=_empty_values)
    _attempt_edges: tuple[FlowResolvedInputEdge, ...] | None = None
    _facts: ForwardingFacts | None = None
    _completed_calls: int = 0

    def hold_selected_value(
        self, selection: FlowResolvedInputHashedSelection, value: object
    ) -> None:
        self._values.setdefault((selection.encoding, selection.sha256), value)

    def hold_attempt_edges(self, edges: Sequence[FlowResolvedInputEdge]) -> None:
        self._attempt_edges = tuple(edges)

    def record_completed_call(
        self, *, edge_indexes: Sequence[int] | None, output_text: str
    ) -> None:
        self._completed_calls += 1
        if self._completed_calls > 1 or edge_indexes is None:
            return
        edges = self._attempt_edges
        if edges is None:
            return
        segments: list[ForwardingSegment] = []
        unmeasured: list[int] = []
        for index in edge_indexes:
            text = self._segment_text(edges[index]) if 0 <= index < len(edges) else None
            if text is None:
                unmeasured.append(index)
            else:
                segments.append(ForwardingSegment(edge_index=index, text=text))
        self._facts = measure_forwarding_facts(
            segments=segments,
            output_text=output_text,
            unmeasured_edge_indexes=unmeasured,
            clock=self.clock or time.perf_counter,
        )

    def facts(self) -> ForwardingFacts | None:
        """The facts of the first completed model call, with the attempt's
        call count; None when no model call returned output."""
        if self._facts is None:
            return None
        return self._facts.model_copy(update={"call_count": self._completed_calls})

    def _segment_text(self, edge: FlowResolvedInputEdge) -> str | None:
        selection = edge.selection
        if not isinstance(selection, FlowResolvedInputHashedSelection):
            return None
        key = (selection.encoding, selection.sha256)
        if key not in self._values:
            return None
        value = self._values[key]
        if isinstance(value, str):
            return value
        return canonical_json_bytes(value).decode("utf-8")


_capture: ContextVar[ForwardingCapture | None] = ContextVar(
    "flow_forwarding_capture", default=None
)


@contextmanager
def forwarding_capture_scope(
    clock: Clock | None = None,
) -> Generator[ForwardingCapture]:
    """Capture the forwarding of one step attempt."""
    capture = ForwardingCapture(clock=clock)
    token = _capture.set(capture)
    try:
        with observe_selected_values(capture.hold_selected_value):
            yield capture
    finally:
        _capture.reset(token)


def hold_attempt_edges(edges: Sequence[FlowResolvedInputEdge]) -> None:
    """The attempt's resolved input edges, as activation records them."""
    capture = _capture.get()
    if capture is not None:
        capture.hold_attempt_edges(edges)


def record_completed_model_call(
    *, edge_indexes: Sequence[int] | None, output_text: str
) -> None:
    """A model call of the attempt returned ``output_text``. Never raises."""
    capture = _capture.get()
    if capture is None:
        return
    try:
        capture.record_completed_call(
            edge_indexes=edge_indexes, output_text=output_text
        )
    except Exception as exc:
        logger.warning(
            "flow_forwarding_facts.capture_failed error_type=%s",
            type(exc).__name__,
        )


__all__ = [
    "ForwardingCapture",
    "forwarding_capture_scope",
    "hold_attempt_edges",
    "record_completed_model_call",
]
