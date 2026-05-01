import { describe, expect, it } from "vitest";

import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
import { FlowRunLaunchInputState } from "./FlowRunLaunchInputState.svelte";

function field(
  name: string,
  overrides: Partial<NormalizedFlowFormField> = {}
): NormalizedFlowFormField {
  return {
    name,
    type: "text",
    required: false,
    options: [],
    order: 1,
    ...overrides
  };
}

describe("FlowRunLaunchInputState", () => {
  it("starts empty and returns defensive form-value snapshots", () => {
    const state = new FlowRunLaunchInputState();

    expect(state.formValuesSnapshot).toEqual({});
    expect(state.freeformText).toBe("");
    expect(state.hasDirtyInput).toBe(false);

    state.setFieldValue(field("name"), "Ada");
    state.setFieldValue(field("roles", { type: "multiselect" }), ["admin"]);
    const snapshot = state.formValuesSnapshot as Record<string, unknown>;
    snapshot.name = "mutated";
    const roles = snapshot.roles;
    if (Array.isArray(roles)) {
      roles.push("mutated");
    }

    expect(state.formValuesSnapshot).toEqual({ name: "Ada", roles: ["admin"] });
  });

  it("updates selected form fields and freeform text without touching other values", () => {
    const state = new FlowRunLaunchInputState();
    state.setFieldValue(field("name"), "Ada");
    state.setFieldValue(field("role"), "Engineer");
    state.setFreeformText("Run this flow");

    expect(state.formValuesSnapshot).toEqual({
      name: "Ada",
      role: "Engineer"
    });
    expect(state.freeformText).toBe("Run this flow");
    expect(state.hasDirtyInput).toBe(true);
  });

  it("replaces state when applying reused input", () => {
    const state = new FlowRunLaunchInputState();
    state.setFieldValue(field("old"), "stale");
    state.setFreeformText("old freeform");

    const input = { name: "Grace", roles: ["admin"] };

    state.applyReusedInput({ formValues: input, freeformText: "new freeform" });
    input.roles.push("mutated");

    expect(state.formValuesSnapshot).toEqual({ name: "Grace", roles: ["admin"] });
    expect(state.freeformText).toBe("new freeform");
  });

  it("treats cleared form and freeform values as not dirty", () => {
    const state = new FlowRunLaunchInputState();
    state.setFieldValue(field("name"), "Ada");
    state.setFieldValue(field("empty"), "   ");
    state.setFreeformText("  ");

    expect(state.hasDirtyInput).toBe(true);

    state.setFieldValue(field("name"), "");

    expect(state.hasDirtyInput).toBe(false);
  });

  it("resets form and freeform state", () => {
    const state = new FlowRunLaunchInputState();
    state.setFieldValue(field("name"), "Ada");
    state.setFreeformText("Run this flow");

    state.reset();

    expect(state.formValuesSnapshot).toEqual({});
    expect(state.freeformText).toBe("");
    expect(state.hasDirtyInput).toBe(false);
  });
});
