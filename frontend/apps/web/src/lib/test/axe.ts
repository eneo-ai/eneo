import axe, { type AxeResults, type ElementContext, type RunOptions } from "axe-core";
import { expect } from "vitest";

// Component tests render fragments, not pages: landmark and heading rules
// describe whole documents and would fail every fragment.
const PAGE_LEVEL_RULES = ["region", "landmark-one-main", "page-has-heading-one"];

function describeViolations(violations: AxeResults["violations"]): string {
  return violations
    .map((violation) => {
      const targets = violation.nodes.map((node) => node.target.join(" ")).join("\n    ");
      return `${violation.id} (${violation.impact}): ${violation.help}\n    ${targets}`;
    })
    .join("\n");
}

// Contrast is measured on the colours drawn now, so an intro transition that fades
// in (such as the page title's) fails it midway. Only running, finite animations are
// awaited: endless ones (spinners) never end, and finished ones that keep their end
// state (`fill: forwards`) or paused ones would never settle.
async function finishTransitions(): Promise<void> {
  // A transition can start a frame after the render that caused it.
  for (let round = 0; round < 10; round++) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const ending = document.getAnimations().filter((animation) => {
      if (animation.playState !== "running") return false;
      const end = animation.effect?.getComputedTiming().endTime;
      return typeof end === "number" && Number.isFinite(end);
    });
    if (ending.length === 0) return;
    await Promise.all(ending.map((animation) => animation.finished.catch(() => undefined)));
  }
}

/** Fails the test when axe finds a WCAG violation inside `context`. */
export async function expectNoAxeViolations(
  context: ElementContext = document,
  options: RunOptions = {}
): Promise<void> {
  await finishTransitions();
  const rules = Object.fromEntries(PAGE_LEVEL_RULES.map((rule) => [rule, { enabled: false }]));
  const results = await axe.run(context, {
    ...options,
    rules: { ...rules, ...(options.rules ?? {}) }
  });
  expect(describeViolations(results.violations)).toBe("");
}
