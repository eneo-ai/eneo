import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import type { Eneo, FlowRunStep } from "@eneo/eneo-js";

import FlowRunEvidenceStepCard from "./FlowRunEvidenceStepCard.svelte";

const result: FlowRunStep = {
  flow_run_id: "00000000-0000-0000-0000-000000000001",
  flow_id: "00000000-0000-0000-0000-000000000002",
  tenant_id: "00000000-0000-0000-0000-000000000003",
  step_id: "00000000-0000-0000-0000-000000000004",
  step_order: 1,
  status: "completed",
  created_at: "2026-07-29T08:00:00Z",
  updated_at: "2026-07-29T08:00:00Z"
};

function renderCard(currentEvidenceNotLoaded: boolean): string {
  return render(FlowRunEvidenceStepCard, {
    props: {
      result,
      currentEvidenceNotLoaded,
      stepDef: undefined,
      duration: null,
      transcription: null,
      runtimeInput: null,
      templateProvenance: null,
      stepRag: null,
      stepAttempts: [],
      copiedKey: null,
      expanded: true,
      panelId: "step-1-panel",
      isPowerUser: false,
      eneo: {} as Eneo,
      onToggle: () => undefined,
      onCopyPayload: async () => undefined,
      onDownloadArtifact: async () => undefined,
      getRuntimeInputSummaryLabel: () => "",
      formatElapsedMs: () => "",
      formatBytes: () => "",
      getCacheStatusLabel: () => ""
    }
  }).body;
}

describe("FlowRunEvidenceStepCard", () => {
  it("shows when the current attempt's evidence was not loaded", () => {
    expect(renderCard(true)).toContain('data-testid="current-evidence-not-loaded"');
  });

  it("omits the notice when the current attempt's evidence was loaded", () => {
    expect(renderCard(false)).not.toContain('data-testid="current-evidence-not-loaded"');
  });
});
