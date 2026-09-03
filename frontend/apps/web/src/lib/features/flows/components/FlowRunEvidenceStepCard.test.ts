import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import type { Eneo, FlowRunStep } from "@eneo/eneo-js";

import FlowRunEvidenceStepCard from "./FlowRunEvidenceStepCard.svelte";
import { m } from "$lib/paraglide/messages";

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

function renderCard(currentEvidenceNotLoaded: boolean, stepResult: FlowRunStep = result): string {
  return render(FlowRunEvidenceStepCard, {
    props: {
      result: stepResult,
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
      formatBytes: () => ""
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

  it("lists who is who once a speaker-mapping step has run", () => {
    const html = renderCard(false, {
      ...result,
      output_payload_json: {
        text: "Fredrik: Hej och välkomna.",
        speaker_mapping: {
          inventory: [
            { label: "SPEAKER_00", line_count: 12, samples: ["Hej och välkomna."] },
            { label: "SPEAKER_01", line_count: 3, samples: ["Tack."] }
          ]
        },
        structured: {
          speakers: [
            {
              label: "SPEAKER_00",
              name: "Fredrik Birging",
              confidence: "high",
              evidence: "Presenterar sig i första repliken."
            },
            { label: "SPEAKER_01", name: null, confidence: "low", evidence: "" }
          ]
        }
        // The `speaker_mapping` extension is the step's persisted payload
        // contract; the generated type only names the common keys.
      } as unknown as FlowRunStep["output_payload_json"]
    });
    expect(html).toContain(m.flow_step_speaker_mapping_section());
    expect(html).toContain("Fredrik Birging");
    expect(html).toContain(m.flow_run_review_speakers_confidence_high());
    expect(html).toContain("Presenterar sig i första repliken.");
    // An unmatched label is named as such rather than left blank.
    expect(html).toContain(m.flow_run_transcript_unknown_speaker());
    expect(html).toContain(m.flow_run_review_speakers_confidence_low());
  });

  it("does not mistake ordinary JSON with a speakers key for a speaker mapping", () => {
    const html = renderCard(false, {
      ...result,
      output_payload_json: {
        text: "{}",
        structured: { speakers: [{ label: "SPEAKER_00", name: "Anna" }] }
      }
    });
    expect(html).not.toContain(m.flow_step_speaker_mapping_section());
  });

  it("renders the attached citation summary for the step result", () => {
    const body = render(FlowRunEvidenceStepCard, {
      props: {
        result: {
          ...result,
          citation_summary: {
            status: "observed",
            sources: [
              { identity_resolved: true, display_name: "Riktlinjer.pdf", container_label: null }
            ],
            matched_cited_source_count: 1,
            sources_truncated: false,
            stale_after_edit: false
          }
        } as FlowRunStep,
        currentEvidenceNotLoaded: false,
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
        formatBytes: () => ""
      }
    }).body;
    expect(body).toContain("Riktlinjer.pdf");
  });
});
