import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
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

/** A transcription, then a step that names its speakers Anna, Bo and Cecilia. */
function evidenceWithNamingStep(): FlowRunEvidenceWithTypedSteps {
  const lines = (first: string, second: string, third: string) =>
    [
      `[00:00:00 - 00:00:04] ${first}: Hej Gunnar.`,
      `[00:00:05 - 00:00:09] ${second}: Jo tack.`,
      `[00:00:10 - 00:00:14] ${third}: Det stämmer.`
    ].join("\n");
  return {
    run: { error: null },
    definition_integrity: {},
    definition_snapshot: {},
    step_results: [
      {
        id: "result-1",
        step_id: "step-transcribe",
        step_order: 1,
        status: "completed",
        input_payload_json: {
          transcription: { file_ids: ["file-1"], source: { attempt_no: 1 } }
        },
        output_payload_json: { text: lines("SPEAKER_00", "SPEAKER_01", "SPEAKER_02") }
      },
      {
        id: "result-2",
        step_id: "step-names",
        step_order: 2,
        status: "completed",
        output_payload_json: {
          text: lines("Anna", "Bo", "Cecilia"),
          speaker_mapping: {
            source_step_id: "step-transcribe",
            inventory: [
              { label: "SPEAKER_00", line_count: 1, samples: ["Hej Gunnar."] },
              { label: "SPEAKER_01", line_count: 1, samples: ["Jo tack."] },
              { label: "SPEAKER_02", line_count: 1, samples: ["Det stämmer."] }
            ]
          },
          structured: {
            speakers: [
              {
                label: "SPEAKER_00",
                name: "Anna",
                confidence: "high",
                evidence: "Presenterar sig som Anna."
              },
              {
                label: "SPEAKER_01",
                name: "Bo",
                confidence: "medium",
                evidence: "Tilltalas som Bo."
              },
              {
                label: "SPEAKER_02",
                name: "Cecilia",
                confidence: "high",
                evidence: "Säger att hon heter Cecilia."
              }
            ]
          }
        }
      }
    ],
    step_attempts: [],
    result_files: [],
    review_checkpoints: [],
    webhook_deliveries: [],
    provider_calls: {},
    debug_export: { run: { summary: {} } }
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

  /**
   * Opens the naming step of a run whose corrections clear the step's Anna
   * and rename its Bo to Bertil, once its transcript shows those names.
   */
  async function openNamingStep() {
    const eneo = eneoReturning(evidenceWithNamingStep());
    Object.assign(eneo.flows.runs, {
      transcriptSource: {
        get: vi.fn(async () => ({
          status: "present",
          source_hash: "a".repeat(64),
          next_segment_index: null,
          speaker_review: null,
          segments: [
            { file_index: 0, start: 0, end: 4, speaker: "SPEAKER_00", text: "Hej Gunnar." },
            { file_index: 0, start: 5, end: 9, speaker: "SPEAKER_01", text: "Jo tack." },
            { file_index: 0, start: 10, end: 14, speaker: "SPEAKER_02", text: "Det stämmer." }
          ]
        }))
      },
      transcriptWords: { get: vi.fn(async () => null) },
      transcriptCorrections: {
        list: vi.fn(async () => [
          {
            step_id: "step-transcribe",
            occurrences: [],
            speaker_edits: [],
            speaker_names: { SPEAKER_00: null, SPEAKER_01: "Bertil" },
            revision: 1,
            stale: false
          }
        ])
      },
      inputFileSignedUrl: vi.fn(async () => ({ url: "https://app.test/f", expires_at: 4102444800 }))
    });
    render(FlowRunEvidence, { runId: "run-1", flowId: "flow-1", eneo, runStatus: "completed" });

    const panel = (order: number) => document.getElementById(`flow-run-step-panel-run-1-${order}`);
    const turn = (order: number, text: string) =>
      within(panel(order)!).getByText(text).closest("[data-turn-index]")?.textContent ?? "";
    await waitFor(() => expect(panel(1)).not.toBeNull());
    await fireEvent.click(
      document.querySelector<HTMLButtonElement>('[aria-controls="flow-run-step-panel-run-1-2"]')!
    );
    await waitFor(() => expect(turn(2, "Jo tack.")).toContain("Bertil"));
    // The naming step's speaker list, one row per label.
    const rows = within(panel(2)!)
      .getAllByRole("listitem")
      .map((row) => row.textContent ?? "");
    return { rows, turn };
  }

  it("names the speakers where a regeneration does: on the naming step, over its names", async () => {
    const { rows, turn } = await openNamingStep();

    // The naming step's list says what its transcript shows.
    expect(rows[0]).toContain(m.flow_run_transcript_unknown_speaker());
    expect(rows[0]).not.toContain("Anna");
    expect(turn(2, "Hej Gunnar.")).toContain(m.flow_transcript_editor_speaker({ number: 1 }));
    expect(rows[1]).toContain("Bertil");
    expect(rows[1]).not.toContain("Bo");

    // The transcription step keeps its labels, as its regenerated text does.
    expect(turn(1, "Jo tack.")).toContain(m.flow_transcript_editor_speaker({ number: 2 }));
    expect(turn(1, "Jo tack.")).not.toContain("Bertil");
  });

  it("does not present the step's support for a name as support for a person's change", async () => {
    const { rows } = await openNamingStep();
    const [cleared, renamed, kept] = rows;
    const confidences = [
      m.flow_run_review_speakers_confidence_high(),
      m.flow_run_review_speakers_confidence_medium(),
      m.flow_run_review_speakers_confidence_low()
    ];

    // The step's confidence and evidence were for Anna and Bo.
    for (const row of [cleared, renamed]) {
      for (const confidence of confidences) expect(row).not.toContain(confidence);
    }
    expect(cleared).toContain(m.flow_run_transcript_unknown_speaker());
    expect(cleared).not.toContain("Presenterar sig som Anna.");
    expect(renamed).toContain("Bertil");
    expect(renamed).not.toContain("Tilltalas som Bo.");

    // A name nobody changed keeps them.
    expect(kept).toContain("Cecilia");
    expect(kept).toContain(m.flow_run_review_speakers_confidence_high());
    expect(kept).toContain("Säger att hon heter Cecilia.");
  });
});
