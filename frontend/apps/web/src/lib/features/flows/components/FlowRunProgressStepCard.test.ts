import { render } from "svelte/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FLOW_API_ERROR_CODE } from "$lib/features/flows/flowRuntimeErrorMapping";
import { m } from "$lib/paraglide/messages";

import FlowRunProgressStepCard from "./FlowRunProgressStepCard.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FlowRunProgressStepCard", () => {
  it("passes step error codes to the shared error alert", () => {
    vi.stubGlobal("window", {
      location: { href: "https://app.example.test/sv/flows/run" },
      matchMedia: () => ({ matches: false })
    });

    const { body } = render(FlowRunProgressStepCard, {
      props: {
        step: {
          stepOrder: 1,
          label: "Extract text",
          status: "failed",
          errorMessage: "Step 1 failed.",
          errorCode: FLOW_API_ERROR_CODE.STEP_EXECUTION_FAILED,
          resultFiles: []
        },
        expanded: true,
        inputExpanded: false,
        copiedKey: null,
        panelId: "step-1-panel",
        onToggle: () => undefined,
        onToggleInput: () => undefined,
        onCopyPayload: async () => undefined,
        onDownloadArtifact: async () => undefined
      }
    });

    expect(body).toContain(m.flow_error_flow_step_execution_failed());
    expect(body).not.toContain(m.flow_run_error_desc());
    expect(body).toContain("Step 1 failed.");
  });
});
