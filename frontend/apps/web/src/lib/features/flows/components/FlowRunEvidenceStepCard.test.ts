import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import type { Eneo, FlowRunStep } from "@eneo/eneo-js";

import FlowRunEvidenceStepCard, {
  type FlowRunTranscriptContext
} from "./FlowRunEvidenceStepCard.svelte";
import { m } from "$lib/paraglide/messages";

const result: FlowRunStep = {
  input_text_aliases: [],
  flow_run_id: "00000000-0000-0000-0000-000000000001",
  flow_id: "00000000-0000-0000-0000-000000000002",
  tenant_id: "00000000-0000-0000-0000-000000000003",
  step_id: "00000000-0000-0000-0000-000000000004",
  step_order: 1,
  status: "completed",
  created_at: "2026-07-29T08:00:00Z",
  updated_at: "2026-07-29T08:00:00Z"
};

function renderCard(
  currentEvidenceNotLoaded: boolean,
  stepResult: FlowRunStep = result,
  transcriptContext: FlowRunTranscriptContext | null = null,
  onRepairFailure: ((stepOrder: number) => void) | null = null,
  runError: { step_order?: number | null } | null = null,
  overrides: {
    stepDef?: Record<string, unknown>;
    isPowerUser?: boolean;
    transcription?: Record<string, unknown>;
    correctionsController?: never;
  } = {}
): string {
  return render(FlowRunEvidenceStepCard, {
    props: {
      result: stepResult,
      runError: runError as never,
      transcriptContext,
      currentEvidenceNotLoaded,
      onRepairFailure,
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
      ...overrides
    }
  }).body;
}

describe("FlowRunEvidenceStepCard", () => {
  it("offers the AI Builder repair for a rejected-output failure and not for other failures", () => {
    const failed = (error_code: FlowRunStep["error_code"]): FlowRunStep => ({
      ...result,
      status: "failed",
      error_code,
      error_message: `Step 1: ${error_code}.`
    });
    const repair = () => undefined;
    expect(renderCard(false, failed("typed_io_output_parse_failed"), null, repair)).toContain(
      m.flow_run_error_repair_action()
    );
    // A candidate code without a handler (no Builder permission) offers nothing.
    expect(renderCard(false, failed("typed_io_output_parse_failed"), null, null)).not.toContain(
      m.flow_run_error_repair_action()
    );
    // A truncated answer is repairable from what the run recorded about it.
    expect(renderCard(false, failed("flow_llm_output_truncated"), null, repair)).toContain(
      m.flow_run_error_repair_action()
    );
    // A failure that happened before the model answered is not a repair.
    expect(
      renderCard(false, failed("typed_io_input_exceeds_model_window"), null, repair)
    ).not.toContain(m.flow_run_error_repair_action());
  });

  it("leads a failed step with what went wrong, before its result and prompt", () => {
    const html = renderCard(false, {
      ...result,
      status: "failed",
      error_code: "typed_io_output_parse_failed",
      error_message: "Step 1: typed_io_output_parse_failed.",
      effective_prompt: "Sammanfatta underlaget.",
      output_payload_json: { text: "Utkast" },
      input_payload_json: { text: "Underlag" }
    });
    const errorAt = html.indexOf(m.flow_run_error());
    expect(errorAt).toBeGreaterThan(-1);
    expect(errorAt).toBeLessThan(html.indexOf(m.flow_run_output()));
    expect(html.indexOf(m.flow_run_output())).toBeLessThan(
      html.indexOf(m.flow_run_effective_prompt())
    );
    // The raw input payload is JSON, which Enkel does not show.
    expect(html).not.toContain(m.flow_run_show_input());
  });

  it("says a step after the one that stopped the run did not run, without repeating the error", () => {
    const skipped: FlowRunStep = {
      ...result,
      step_order: 3,
      status: "failed",
      started_at: null,
      error_code: "typed_io_contract_violation",
      error_message: "Step 2: contract violation."
    };
    const html = renderCard(false, skipped, null, null, { step_order: 2 });
    expect(html).toContain(m.flow_run_step_not_run());
    expect(html).not.toContain("Step 2: contract violation.");
  });

  it("keeps a step that failed before recording its start as the failing step", () => {
    const failedToStart: FlowRunStep = {
      ...result,
      step_order: 2,
      status: "failed",
      started_at: null,
      error_code: "flow_step_attempt_start_failed",
      error_message: "Step 2: attempt could not start."
    };
    const html = renderCard(false, failedToStart, null, null, { step_order: 2 });
    expect(html).not.toContain(m.flow_run_step_not_run());
  });

  it("says how a step that read part by part produced its result", () => {
    const manifest = (ends: number[]) => ({
      character_length: ends[ends.length - 1],
      sections: ends.map((end, index) => ({
        core: { start_char: index === 0 ? 0 : ends[index - 1], end_char: end }
      }))
    });
    const sectioned = (ends: number[]): FlowRunStep => ({
      ...result,
      output_payload_json: { structured: { facts: [] }, section_manifest: manifest(ends) }
    });
    const each = renderCard(false, sectioned([250, 500, 1000]));
    expect(each).toContain(m.flow_run_sections_read_each({ count: "3" }));
    expect(each).not.toContain(m.flow_run_sections_positions());

    const summarizeStep = { input_config: { text_processing: { mode: "summarize" } } };
    expect(
      renderCard(false, sectioned([500, 1000]), null, null, null, { stepDef: summarizeStep })
    ).toContain(m.flow_run_sections_read_summarized({ count: "2" }));

    expect(renderCard(false, sectioned([1000]))).toContain(m.flow_run_sections_read_one());

    const advanced = renderCard(false, sectioned([250, 500, 1000]), null, null, null, {
      isPowerUser: true
    });
    expect(advanced).toContain(m.flow_run_section_position({ index: "3", from: "50", to: "100" }));

    expect(renderCard(false, { ...result, output_payload_json: { structured: {} } })).not.toContain(
      m.flow_run_sections_read_one()
    );
  });

  it("names the speaker identification service that labelled the step, in Avancerad", () => {
    const labelled = { diarization: "external", speaker_service: "Vemsa Sundsvall" };
    const card = (overrides: Parameters<typeof renderCard>[5]) =>
      renderCard(false, result, null, null, null, overrides);

    expect(card({ isPowerUser: true, transcription: labelled })).toContain("Vemsa Sundsvall");
    expect(card({ transcription: labelled })).not.toContain("Vemsa Sundsvall");
    // A step labelled before the service was recorded shows no empty row.
    expect(card({ isPowerUser: true, transcription: { diarization: "external" } })).not.toContain(
      `${m.flow_run_transcription_speaker_service()}</dt>`
    );
  });

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

  // Presentation only. The review checkpoint stores a name the reviewer gave
  // with high confidence and one they cleared with low, both without
  // evidence, which its tests hold; these rows are typed as it stores them.
  it("shows a name a person gave as certain and a cleared one as unknown, without evidence", () => {
    const renderMapping = (speakers: Record<string, unknown>[]) =>
      renderCard(false, {
        ...result,
        output_payload_json: {
          text: "",
          speaker_mapping: {
            inventory: [
              { label: "SPEAKER_00", line_count: 1, samples: ["Hej Gunnar."] },
              { label: "SPEAKER_01", line_count: 1, samples: ["Jo tack."] }
            ]
          },
          structured: { speakers }
        } as unknown as FlowRunStep["output_payload_json"]
      });
    const anna = {
      label: "SPEAKER_00",
      name: "Anna",
      confidence: "high",
      evidence: "Presenterar sig som Anna."
    };
    const bo = {
      label: "SPEAKER_01",
      name: "Bo",
      confidence: "medium",
      evidence: "Tilltalas som Bo."
    };
    const proposed = renderMapping([anna, bo]);
    // What approval stores once the reviewer named Anna's speaker Bertil and
    // cleared Bo's.
    const approved = renderMapping([
      { ...anna, name: "Bertil", confidence: "high", evidence: "" },
      { ...bo, name: null, confidence: "low", evidence: "" }
    ]);
    const count = (html: string, text: string) => html.split(text).length - 1;

    // The step's evidence was for Anna and Bo.
    for (const evidence of [anna.evidence, bo.evidence]) {
      expect(proposed).toContain(evidence);
      expect(approved).not.toContain(evidence);
    }
    expect(approved).toContain("Bertil");
    expect(count(approved, m.flow_run_review_speakers_confidence_high())).toBe(1);
    expect(approved).not.toContain(m.flow_run_review_speakers_confidence_medium());
    // Bo's speaker reads as any unknown speaker does.
    expect(approved).toContain(m.flow_run_transcript_unknown_speaker());
    expect(count(approved, m.flow_run_review_speakers_confidence_low())).toBe(1);
  });

  // The transcription step's stored segments carry raw labels; which card may
  // render them decides whether names show up downstream.
  const rawContext: FlowRunTranscriptContext = {
    fileIds: ["file-1"],
    stepId: result.step_id,
    segments: [
      { index: 0, fileIndex: 0, start: 0, end: 4, speaker: "SPEAKER_00", text: "Hej Gunnar." },
      { index: 1, fileIndex: 0, start: 5, end: 9, speaker: "SPEAKER_01", text: "Jo tack." }
    ],
    getAudioUrl: () => Promise.reject(new Error("unused"))
  };

  it("renders the transcription step from the stored segments", () => {
    const html = renderCard(
      false,
      { ...result, output_payload_json: { text: "[00:00:00 - 00:00:04] SPEAKER_00: Hej Gunnar." } },
      rawContext
    );
    // A raw diarization label is presented to the reviewer as a speaker name.
    expect(html).toContain(m.flow_transcript_editor_speaker({ number: 1 }));
    // The second line exists only in the stored segments, not in this step's
    // own output text, so finding it proves the segments were rendered.
    expect(html).toContain("Jo tack.");
  });

  it("renders a downstream step's own renamed transcript, not the raw segments", () => {
    const html = renderCard(
      false,
      {
        ...result,
        step_id: "00000000-0000-0000-0000-000000000009",
        step_order: 4,
        output_payload_json: {
          text: [
            "[00:00:00 - 00:00:04] Handläggare: Hej Gunnar.",
            "[00:00:05 - 00:00:09] Gunnar: Jo tack."
          ].join("\n")
        }
      },
      rawContext
    );
    expect(html).toContain("Handläggare");
    // Its own names, not the transcription step's numbered fallback.
    expect(html).not.toContain(m.flow_transcript_editor_speaker({ number: 1 }));
  });

  // A person's names, kept with the transcription step's corrections.
  const named = (speakerNames: Record<string, string | null>) =>
    ({ error: null, staleCount: 0, occurrences: [], speakerEdits: [], speakerNames }) as never;

  it("shows the names a person gave on the stored segments", () => {
    const transcription = renderCard(
      false,
      { ...result, output_payload_json: { text: "[00:00:00 - 00:00:04] SPEAKER_00: Hej Gunnar." } },
      rawContext,
      null,
      null,
      { correctionsController: named({ SPEAKER_00: "Gunnar Ek", SPEAKER_01: null }) }
    );
    expect(transcription).toContain("Gunnar Ek");
    expect(transcription).toContain(m.flow_transcript_editor_speaker({ number: 2 }));

    // Over the speaker-naming step's names, the same rule a regeneration uses.
    const naming = renderCard(
      false,
      {
        ...result,
        step_id: "00000000-0000-0000-0000-000000000009",
        step_order: 2,
        output_payload_json: {
          text: "[00:00:00 - 00:00:04] Gunnar: Hej Gunnar.",
          speaker_mapping: {
            inventory: [
              { label: "SPEAKER_00", line_count: 1, samples: ["Hej Gunnar."] },
              { label: "SPEAKER_01", line_count: 1, samples: ["Jo tack."] }
            ]
          },
          structured: {
            speakers: [
              { label: "SPEAKER_00", name: "Gunnar", confidence: "high", evidence: "" },
              { label: "SPEAKER_01", name: "Handläggare", confidence: "low", evidence: "" }
            ]
          }
        } as unknown as FlowRunStep["output_payload_json"]
      },
      rawContext,
      null,
      null,
      { correctionsController: named({ SPEAKER_00: "Gunnar Ek" }) }
    );
    expect(naming).toContain("Gunnar Ek");

    // A downstream step's own transcript is shown as it was written.
    const downstream = renderCard(
      false,
      {
        ...result,
        step_id: "00000000-0000-0000-0000-000000000010",
        step_order: 3,
        output_payload_json: { text: "[00:00:00 - 00:00:04] SPEAKER_00: Hej Gunnar." }
      },
      rawContext,
      null,
      null,
      { correctionsController: named({ SPEAKER_00: "Gunnar Ek" }) }
    );
    expect(downstream).not.toContain("Gunnar Ek");
  });

  it("presents a name a person gave or cleared after the run as a review stores it", () => {
    // The card's speaker list; its raw output below shows what the step stored.
    const speakerList = (speakerNames: Record<string, string | null>) => {
      const html = renderCard(
        false,
        {
          ...result,
          step_id: "00000000-0000-0000-0000-000000000009",
          step_order: 2,
          output_payload_json: {
            text: "[00:00:00 - 00:00:04] Anna: Hej Gunnar.\n[00:00:05 - 00:00:09] Bo: Jo tack.",
            speaker_mapping: {
              inventory: [
                { label: "SPEAKER_00", line_count: 1, samples: ["Hej Gunnar."] },
                { label: "SPEAKER_01", line_count: 1, samples: ["Jo tack."] }
              ]
            },
            structured: {
              speakers: [
                {
                  label: "SPEAKER_00",
                  name: "Anna",
                  confidence: "medium",
                  evidence: "Presenterar sig som Anna."
                },
                {
                  label: "SPEAKER_01",
                  name: "Bo",
                  confidence: "medium",
                  evidence: "Tilltalas som Bo."
                }
              ]
            }
          } as unknown as FlowRunStep["output_payload_json"]
        },
        rawContext,
        null,
        null,
        { correctionsController: named(speakerNames) }
      );
      const start = html.indexOf(`>${m.flow_step_speaker_mapping_section()}</h4>`);
      expect(start).toBeGreaterThan(-1);
      return html.slice(start, html.indexOf("</ul>", start));
    };
    const count = (html: string, text: string) => html.split(text).length - 1;
    const medium = m.flow_run_review_speakers_confidence_medium();

    // A name a person gives is certain; the step's evidence was for Anna.
    const renamed = speakerList({ SPEAKER_00: "Bertil" });
    expect(renamed).toContain("Bertil");
    expect(count(renamed, m.flow_run_review_speakers_confidence_high())).toBe(1);
    expect(renamed).not.toContain("Presenterar sig som Anna.");
    // The name nobody changed keeps the step's support.
    expect(count(renamed, medium)).toBe(1);
    expect(renamed).toContain("Tilltalas som Bo.");

    // A name a person clears leaves an unknown speaker, as the step leaves one.
    const cleared = speakerList({ SPEAKER_01: null });
    expect(cleared).toContain(m.flow_run_transcript_unknown_speaker());
    expect(count(cleared, m.flow_run_review_speakers_confidence_low())).toBe(1);
    expect(cleared).not.toContain("Tilltalas som Bo.");
    expect(count(cleared, medium)).toBe(1);
  });

  it("shows a downstream document as authored when it only quotes transcript lines", () => {
    const html = renderCard(
      false,
      {
        ...result,
        step_id: "00000000-0000-0000-0000-000000000009",
        step_order: 4,
        output_payload_json: {
          text: [
            "# Samtal om hemtjänst",
            "",
            "[00:00:00 - 00:00:04] Handläggare: Hej Gunnar."
          ].join("\n")
        }
      },
      rawContext
    );
    expect(html).toContain("Samtal om hemtjänst");
    expect(html).not.toContain("SPEAKER_00");
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
