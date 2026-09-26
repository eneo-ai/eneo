"use client";

import { FieldStatus } from "@astryxdesign/core/FieldStatus";

/*
 * A form's problems show at their fields once it is submitted, and focus
 * moves to the first (ACCESSIBILITY.md → Forms, WCAG 3.3.1): the submit
 * button stays enabled, since a disabled one says nothing about what is
 * missing. Astryx fields take `status`; these are for legacy controls
 * (Input, Textarea, a Select's trigger).
 */

const problemId = (id: string) => `${id}-problem`;

/** The problem under a legacy control, as Astryx shows a field's status. */
export function FieldProblem({ id, problem }: { id: string; problem: string | null }) {
  if (!problem) return null;
  return <FieldStatus type="error" variant="detached" message={problem} id={problemId(id)} />;
}

/**
 * The control's side of FieldProblem: aria-invalid, and aria-describedby
 * naming the problem before any description it already has.
 */
export function fieldProblemProps(id: string, problem: string | null, describedBy?: string) {
  const ids = [problem ? problemId(id) : null, describedBy].filter(Boolean).join(" ");
  return { "aria-invalid": problem ? true : undefined, "aria-describedby": ids || undefined };
}
