import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Eneo, FlowRunEvidenceWithTypedSteps } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import FlowRunEvidence from "./FlowRunEvidence.svelte";

vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => writable("user")
}));
vi.mock("$lib/components/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));
import { EneoError } from "@eneo/eneo-js";
import { toast } from "$lib/components/toast";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function evidenceWithCorruptPassageAggregates(
  countTruncated: boolean
): FlowRunEvidenceWithTypedSteps {
  return {
    run: { error: null },
    definition_integrity: {},
    definition_snapshot: {},
    step_results: [],
    step_attempts: [],
    result_files: [],
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
            attempts_not_loaded: countTruncated ? 500 : 2,
            corrupt_passage_aggregates: 2,
            current_attempts_not_loaded: countTruncated ? 2 : 1,
            current_step_orders_not_loaded: [3],
            count_truncated: countTruncated
          }
        }
      }
    }
  } as unknown as FlowRunEvidenceWithTypedSteps;
}

function evidenceWithBoundedSections(): FlowRunEvidenceWithTypedSteps {
  const evidence = evidenceWithCorruptPassageAggregates(false);
  evidence.debug_export!.run!.summary!.knowledge_evidence_view = undefined;
  evidence.debug_export!.run!.summary!.omissions = [
    {
      reason: "row_limit",
      section: "step_results",
      rows_omitted: 3,
      count_truncated: true
    },
    {
      reason: "logical_bytes",
      section: "result_files",
      rows_omitted: 2,
      count_truncated: false
    }
  ];
  return evidence;
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
  it("tells a refused result file download by its own reason", async () => {
    // Kills the mutant that answers every failed download with the fixed
    // sentence: a file purged since this view loaded would look broken.
    const evidence = evidenceWithBoundedSections();
    evidence.result_files = [
      { file_id: "file-1", name: "Plan.pdf", availability: "available" }
    ] as FlowRunEvidenceWithTypedSteps["result_files"];
    const eneo = eneoReturning(evidence);
    eneo.flows.runs.artifactSignedUrl = vi.fn().mockRejectedValue(
      new EneoError("gone", "RESPONSE", 410, 9056, {
        code: "flow_run_artifact_content_unavailable"
      })
    );
    render(FlowRunEvidence, { runId: "run-1", flowId: "flow-1", eneo, runStatus: "completed" });

    await fireEvent.click(
      await screen.findByRole("button", {
        name: m.flow_run_download_artifact({ name: "Plan.pdf" })
      })
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(m.flow_error_flow_run_artifact_content_unavailable())
    );
  });

  it("offers a retry when the evidence request fails, and loads on retry", async () => {
    const consoleError = vi.spyOn(console, "error");
    const evidence = vi
      .fn()
      .mockRejectedValueOnce(new Error("PRIVATE_SYNTHETIC_ERROR_PAYLOAD"))
      .mockResolvedValueOnce(evidenceWithBoundedSections());
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: { flows: { runs: { evidence } } } as unknown as Eneo,
      runStatus: "completed"
    });

    expect(await screen.findByText(m.flow_run_evidence_error())).toBeTruthy();
    expect(consoleError).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_retry() }));
    await waitFor(() => expect(evidence).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("evidence-view-omissions")).toBeTruthy();
    expect(screen.queryByText(m.flow_run_evidence_error())).toBeNull();
  });

  it("marks every attempt-derived count as a lower bound when truncated", async () => {
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: eneoReturning(evidenceWithCorruptPassageAggregates(true)),
      runStatus: "completed"
    });

    expect(
      await screen.findByText(m.flow_run_knowledge_view_attempts_not_loaded({ count: "≥500" }))
    ).toBeTruthy();
    expect(
      screen.getByText(m.flow_run_knowledge_view_corrupt_passage_aggregates({ count: "≥2" }))
    ).toBeTruthy();
    expect(
      screen.getByText(
        m.flow_run_knowledge_view_current_attempts_not_loaded({
          count: "≥2",
          steps: "3"
        })
      )
    ).toBeTruthy();
    expect(screen.getByText(/bland annat steg nummer 3\./)).toBeTruthy();
  });

  it("renders exact attempt-derived counts without a lower-bound marker", async () => {
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: eneoReturning(evidenceWithCorruptPassageAggregates(false)),
      runStatus: "completed"
    });

    expect(
      await screen.findByText(m.flow_run_knowledge_view_attempts_not_loaded({ count: "2" }))
    ).toBeTruthy();
    expect(
      screen.getByText(m.flow_run_knowledge_view_corrupt_passage_aggregates({ count: "2" }))
    ).toBeTruthy();
    expect(
      screen.getByText(
        m.flow_run_knowledge_view_current_attempts_not_loaded({
          count: "1",
          steps: "3"
        })
      )
    ).toBeTruthy();
  });

  it("reports every section omitted from the bounded view", async () => {
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: eneoReturning(evidenceWithBoundedSections()),
      runStatus: "completed"
    });

    expect(await screen.findByTestId("evidence-view-omissions")).toBeTruthy();
    expect(
      screen.getByText(
        m.flow_run_evidence_view_rows_omitted({
          section: m.flow_run_evidence_section_step_results(),
          count: "≥3"
        })
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        m.flow_run_evidence_view_bytes_omitted({
          section: m.flow_run_evidence_section_result_files(),
          count: "2"
        })
      )
    ).toBeTruthy();
  });
});
