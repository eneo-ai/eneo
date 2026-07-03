import { describe, expect, it } from "vitest";

import { FLOW_API_ERROR_CODE } from "@eneo/eneo-js";
import type { FlowRunContractTemplateReadiness } from "@eneo/eneo-js";
import type { FlowRunDialogLabels } from "./flowRunDialogLabels";
import { getFlowRuntimeErrorMessageByCode } from "$lib/features/flows/flowRuntimeErrorMapping";
import {
  getTemplateReadinessMessage,
  getTemplateStatusClasses,
  getTemplateStatusLabel
} from "./flowRunTemplateStatus";

const labels = {
  templateReady: "Ready",
  templateNeedsAction: "Needs action",
  templateReadOnly: "Read-only",
  templateUnavailable: "Unavailable",
  templateReadOnlyMessage: "You can run the flow but you cannot change the template.",
  templateNeedsActionMessage: "The template needs attention before the flow can run."
} as unknown as FlowRunDialogLabels;

function readinessItem(
  overrides: Partial<FlowRunContractTemplateReadiness>
): FlowRunContractTemplateReadiness {
  return {
    step_id: "step-1",
    template_name: null,
    status: "ready",
    message_code: null,
    ...overrides
  } as FlowRunContractTemplateReadiness;
}

describe("getTemplateStatusLabel", () => {
  it("maps known statuses to their label", () => {
    expect(getTemplateStatusLabel("ready", labels)).toBe("Ready");
    expect(getTemplateStatusLabel("needs_action", labels)).toBe("Needs action");
    expect(getTemplateStatusLabel("read_only", labels)).toBe("Read-only");
  });

  it("falls back to the unavailable label for unknown statuses", () => {
    expect(getTemplateStatusLabel(null, labels)).toBe("Unavailable");
    expect(getTemplateStatusLabel("something-else", labels)).toBe("Unavailable");
  });
});

describe("getTemplateStatusClasses", () => {
  it("returns the positive palette for ready", () => {
    expect(getTemplateStatusClasses("ready")).toContain("text-positive-stronger");
  });

  it("returns the negative palette for unknown statuses", () => {
    expect(getTemplateStatusClasses(null)).toContain("text-negative-stronger");
  });
});

describe("getTemplateReadinessMessage", () => {
  it("returns no message for a ready template", () => {
    expect(getTemplateReadinessMessage(readinessItem({ status: "ready" }), labels)).toBeNull();
  });

  it("returns the read-only message for a read-only template", () => {
    expect(getTemplateReadinessMessage(readinessItem({ status: "read_only" }), labels)).toBe(
      "You can run the flow but you cannot change the template."
    );
  });

  it("prefers a resolved message_code over the status fallback", () => {
    const code = FLOW_API_ERROR_CODE.REVIEW_POLICY_INVALID;
    const mapped = getFlowRuntimeErrorMessageByCode(code);
    expect(mapped).not.toBeNull();
    const item = readinessItem({ status: "needs_action", message_code: code });
    expect(getTemplateReadinessMessage(item, labels)).toBe(mapped);
    expect(getTemplateReadinessMessage(item, labels)).not.toBe(labels.templateNeedsActionMessage);
  });

  it("falls back to the needs-action message when no code resolves", () => {
    expect(
      getTemplateReadinessMessage(
        readinessItem({ status: "needs_action", message_code: null }),
        labels
      )
    ).toBe("The template needs attention before the flow can run.");
  });
});
