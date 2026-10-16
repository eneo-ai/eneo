import axe, { type AxeResults, type RunOptions } from "axe-core";
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

/** Fails the test when axe finds a WCAG violation inside `context`. */
export async function expectNoAxeViolations(
  context: Element | Document = document,
  options: RunOptions = {}
): Promise<void> {
  const rules = Object.fromEntries(PAGE_LEVEL_RULES.map((rule) => [rule, { enabled: false }]));
  const results = await axe.run(context, {
    ...options,
    rules: { ...rules, ...(options.rules ?? {}) }
  });
  expect(describeViolations(results.violations)).toBe("");
}
