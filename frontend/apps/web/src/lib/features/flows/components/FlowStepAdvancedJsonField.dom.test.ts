import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, expect, test } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { AdvancedJsonProblem } from "./advancedJsonDrafts";
import FlowStepAdvancedJsonField from "./FlowStepAdvancedJsonField.svelte";

afterEach(cleanup);

// Kills: one sentence for both problems. "Check commas and brackets" is false
// for a well-formed list, and "must be an object" is false for a typo.
test.each<[AdvancedJsonProblem, string, () => string, () => string]>([
  ["syntax", "{invalid", m.flow_step_json_parse_error, m.flow_step_json_not_object],
  ["not_object", "[1, 2]", m.flow_step_json_not_object, m.flow_step_json_parse_error]
])("a %s problem is named with its own sentence", (error, value, shown, absent) => {
  render(FlowStepAdvancedJsonField, {
    field: "output_config",
    stepOrder: 2,
    value,
    error,
    isPublished: false,
    placeholder: ""
  });

  expect(screen.getByRole("textbox").getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByRole("status").textContent?.trim()).toBe(shown());
  expect(screen.queryByText(absent())).toBeNull();
});
