"use client";

import { FieldStatus } from "@astryxdesign/core/FieldStatus";
import { flushSync } from "react-dom";

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

/**
 * Submit time: `reveal` renders the problems (synchronously), then focus moves
 * to `target` (an element or its id), so the field is read with its error. A
 * closed `<details>` around it opens; a fieldset hands focus to its first
 * enabled input.
 */
export function revealProblems(
  reveal: () => void,
  target: HTMLElement | string | null | undefined
) {
  flushSync(reveal);
  const element = typeof target === "string" ? document.getElementById(target) : target;
  if (!element) return;
  for (
    let details = element.closest("details");
    details;
    details = details.parentElement?.closest("details") ?? null
  ) {
    details.open = true;
  }
  (element instanceof HTMLFieldSetElement
    ? element.querySelector<HTMLElement>("input:enabled")
    : element
  )?.focus();
}
