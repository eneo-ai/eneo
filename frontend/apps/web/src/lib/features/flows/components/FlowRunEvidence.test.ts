// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Eneo, FlowRunEvidenceWithTypedSteps } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import FlowRunEvidence from "./FlowRunEvidence.svelte";

vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => writable("user")
}));

afterEach(() => {
  cleanup();
});

function evidenceWithCorruptPassageAggregates(): FlowRunEvidenceWithTypedSteps {
  return {
    run: { error: null },
    definition_integrity: {},
    definition_snapshot: {},
    step_results: [],
    step_attempts: [],
    result_files: [],
    rerun_operations: [],
    rerun_invalidated_steps: [],
    review_checkpoints: [],
    webhook_deliveries: [],
    provider_calls: {},
    debug_export: {
      run: {
        summary: {
          knowledge_evidence_view: {
            byte_budget: 1024,
            returned_passage_bytes: 0,
            passages_omitted: 0,
            passage_bytes_omitted: 0,
            attempts_with_omitted_passages: 0,
            attempts_not_loaded: 2,
            corrupt_passage_aggregates: 2
          }
        }
      }
    }
  } as unknown as FlowRunEvidenceWithTypedSteps;
}

function eneoReturning(evidence: FlowRunEvidenceWithTypedSteps): Eneo {
  return {
    flows: {
      runs: {
        evidence: vi.fn().mockResolvedValue(evidence)
      }
    }
  } as unknown as Eneo;
}

describe("FlowRunEvidence", () => {
  it("reports corrupt attempts within the not-loaded total", async () => {
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: eneoReturning(evidenceWithCorruptPassageAggregates()),
      runStatus: "completed"
    });

    expect(
      await screen.findByText(m.flow_run_knowledge_view_attempts_not_loaded({ count: "2" }))
    ).toBeTruthy();
    expect(
      screen.getByText(m.flow_run_knowledge_view_corrupt_passage_aggregates({ count: "2" }))
    ).toBeTruthy();
  });
});
