import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components, Eneo, FlowRunEvidenceWithTypedSteps } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import { formatDateTime } from "$lib/core/formatting/dateTime";
import FlowRunEvidence from "./FlowRunEvidence.svelte";

vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => writable("user")
}));

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
    released_inputs: [],
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

function eneoReturning(
  evidence: FlowRunEvidenceWithTypedSteps,
  releasedInputs: components["schemas"]["FlowRunReleasedInput"][] = []
): Eneo {
  return {
    flows: {
      runs: {
        evidence: vi.fn().mockResolvedValue({ ...evidence, released_inputs: releasedInputs }),
        get: vi.fn().mockResolvedValue({ released_inputs: releasedInputs })
      }
    }
  } as unknown as Eneo;
}

describe("FlowRunEvidence", () => {
  it("offers a retry when the evidence request fails, and loads on retry", async () => {
    const consoleError = vi.spyOn(console, "error");
    const evidence = vi
      .fn()
      .mockRejectedValueOnce(new Error("PRIVATE_SYNTHETIC_ERROR_PAYLOAD"))
      .mockResolvedValueOnce(evidenceWithBoundedSections());
    render(FlowRunEvidence, {
      runId: "run-1",
      flowId: "flow-1",
      eneo: {
        flows: { runs: { evidence, get: vi.fn().mockResolvedValue({ released_inputs: [] }) } }
      } as unknown as Eneo,
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
    expect(screen.getByText(/bland annat 3\./)).toBeTruthy();
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

  it.each([false, true])(
    "reports bounded sections and durable audio deletion (released=%s)",
    async (released) => {
      const eneo = eneoReturning(
        evidenceWithBoundedSections(),
        released
          ? [
              {
                step_id: "step-1",
                file_id: "file-1",
                released_at: "2026-10-06T12:34:00Z",
                reason: "transcription_audio_after_use"
              }
            ]
          : []
      );
      render(FlowRunEvidence, {
        runId: "run-1",
        flowId: "flow-1",
        eneo,
        runStatus: released ? "failed" : "completed"
      });

      // Kills omitting the durable release state or displaying deletion for a retained file.
      await screen.findByTestId("evidence-view-omissions");
      // Kills G5-E02: a second detail request creates a duplicate required read audit.
      expect(eneo.flows.runs.evidence).toHaveBeenCalledTimes(1);
      expect(eneo.flows.runs.get).not.toHaveBeenCalled();
      const deletionLabel = m.flow_run_audio_deleted_after_use({
        date: formatDateTime("2026-10-06T12:34:00Z")
      });
      expect(screen.queryByText(deletionLabel) !== null).toBe(released);
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
    }
  );
});
