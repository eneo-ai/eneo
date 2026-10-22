import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import {
  blockingTemplates,
  exceedsAggregate,
  fieldProblem,
  inputPayload,
  inputProblem,
  labelsSpeakers,
  offersMaxSpeakers,
  offersSingleRecording,
  orderedFields,
  recordedAsOne,
  refusalTargets,
  runRequest,
  speakersBlockRun,
  takesFreeText,
  type UploadEntry
} from "./run-contract";
import { makeContract, makeInput } from "./run-fixtures";
import type { RunFormField } from "./runs-api";

const field = (overrides: Partial<RunFormField>): RunFormField => ({
  name: "namn",
  type: "text",
  required: false,
  ...overrides
});

const done = (fileId: string): UploadEntry => ({
  key: fileId,
  name: `${fileId}.pdf`,
  size: 10,
  mimetype: "application/pdf",
  state: "done",
  fileId
});

describe("orderedFields", () => {
  it("orders by `order`, then as listed", () => {
    const contract = makeContract({
      form_fields: [
        field({ name: "c", order: 3 }),
        field({ name: "b" }),
        field({ name: "a", order: 1 })
      ]
    });
    expect(orderedFields(contract).map((item) => item.name)).toEqual(["a", "b", "c"]);
  });
});

describe("fieldProblem", () => {
  it("asks for a required value, single or several", () => {
    expect(fieldProblem(field({ required: true }), "  ")).toBe("required");
    expect(fieldProblem(field({ required: true, type: "list" }), ["", " "])).toBe("required");
    expect(fieldProblem(field({ required: false }), "")).toBeNull();
  });

  it("checks numbers, dates and choices as the core does", () => {
    expect(fieldProblem(field({ type: "number" }), "12.5")).toBeNull();
    expect(fieldProblem(field({ type: "number" }), "tolv")).toBe("number");
    expect(fieldProblem(field({ type: "date" }), "2026-02-30")).toBe("date");
    expect(fieldProblem(field({ type: "date" }), "2026-10-21")).toBeNull();
    expect(fieldProblem(field({ type: "select", options: ["Ja"] }), "Nej")).toBe("option");
    expect(fieldProblem(field({ type: "multiselect", options: ["A", "B"] }), ["A", "C"])).toBe(
      "option"
    );
  });
});

describe("inputPayload", () => {
  it("sends each field by name; an empty optional number or choice is null", () => {
    const contract = makeContract({
      form_fields: [
        field({ name: "text", type: "text" }),
        field({ name: "antal", type: "number" }),
        field({ name: "val", type: "select", options: ["A"] }),
        field({ name: "lista", type: "list" })
      ]
    });
    expect(
      inputPayload(contract, { text: "Hej", antal: "3", val: "", lista: ["a", " ", "b "] }, "")
    ).toEqual({ text: "Hej", antal: 3, val: null, lista: ["a", "b"] });
  });

  it("sends free text when the flow has neither fields nor uploads", () => {
    const contract = makeContract({ form_fields: [], steps_requiring_input: [] });
    expect(takesFreeText(contract)).toBe(true);
    expect(inputPayload(contract, {}, "Brevet")).toEqual({ text: "Brevet" });
  });
});

describe("inputProblem", () => {
  const input = makeInput({ required: true, max_files: 2 });

  it("waits for uploads and names a failed one", () => {
    expect(inputProblem(input, [{ ...done("a"), state: "uploading" }])).toBe("uploading");
    expect(inputProblem(input, [done("a"), { ...done("b"), state: "failed" }])).toBe("failed");
  });

  it("asks for a required file and keeps to the step's count", () => {
    expect(inputProblem(input, [])).toBe("required");
    expect(inputProblem(input, [done("a"), done("b"), done("c")])).toBe("too_many");
    expect(inputProblem(input, [done("a")])).toBeNull();
  });

  it("counts every step's files against the flow's total", () => {
    const contract = makeContract({ aggregate_max_files: 2 });
    expect(exceedsAggregate(contract, { s1: [done("a")], s2: [done("b"), done("c")] })).toBe(true);
    expect(exceedsAggregate({ aggregate_max_files: null }, { s1: [done("a")] })).toBe(false);
  });
});

describe("blocking states", () => {
  it("blocks on templates that need action or are unavailable", () => {
    const contract = makeContract({
      template_readiness: [
        { step_id: "s1", status: "ready" },
        { step_id: "s2", status: "read_only" },
        { step_id: "s3", status: "needs_action", template_name: "Beslut" }
      ]
    });
    expect(blockingTemplates(contract).map((item) => item.step_id)).toEqual(["s3"]);
  });

  it("blocks only when speaker labels are required and unavailable", () => {
    const transcription = (required: boolean) =>
      makeContract({
        transcription: {
          live: { available: false },
          speaker_labels: {
            default: true,
            required,
            selectable: false,
            unavailable_reason: "not_chosen"
          }
        }
      });
    expect(speakersBlockRun(transcription(true))).toBe(true);
    expect(speakersBlockRun(transcription(false))).toBe(false);
  });
});

describe("runRequest", () => {
  const audio = makeInput({ step_id: "s1", input_format: "audio", required: true });
  const contract = makeContract({
    published_flow_version: 7,
    form_fields: [field({ name: "ärende", required: true })],
    steps_requiring_input: [audio],
    transcription: {
      live: { available: false },
      single_recording: true,
      max_speakers: { default: 4, form_field: null, participants_field: null },
      speaker_labels: {
        default: false,
        required: false,
        selectable: true,
        unavailable_reason: null
      }
    }
  });

  it("pins the published version and sends files per step", () => {
    const body = runRequest(contract, {
      values: { ärende: "Bygglov" },
      freeText: "",
      uploads: { s1: [done("f1"), done("f2")] },
      singleRecording: new Set(["s1"]),
      speakerLabels: true,
      maxSpeakers: 3
    });
    expect(body).toEqual({
      expected_flow_version: 7,
      input_payload_json: { ärende: "Bygglov" },
      step_inputs: { s1: { file_ids: ["f1", "f2"], single_recording: true } },
      speaker_labels: true,
      max_speakers: 3
    });
  });

  it("leaves out choices the person did not make or the flow does not offer", () => {
    const body = runRequest(contract, {
      values: { ärende: "Bygglov" },
      freeText: "",
      uploads: { s1: [done("f1")] },
      singleRecording: new Set(["s1"]),
      speakerLabels: null,
      maxSpeakers: 3
    });
    // One file is not "parts of a recording"; speakers are off by default, so no bound.
    expect(body).toEqual({
      expected_flow_version: 7,
      input_payload_json: { ärende: "Bygglov" },
      step_inputs: { s1: { file_ids: ["f1"] } }
    });
    expect(labelsSpeakers(contract, null)).toBe(false);
    expect(offersMaxSpeakers(contract, null)).toBe(false);
    expect(offersSingleRecording(contract, audio, [done("f1")])).toBe(false);
  });

  it("sends the parts of one recording made in the form as one, without asking", () => {
    const part = (fileId: string, index: number): UploadEntry => ({
      ...done(fileId),
      recording: { sessionId: "rec-1", index, durationMs: 60_000 }
    });
    const parts = [part("f1", 0), part("f2", 1)];
    expect(recordedAsOne(parts)).toBe(true);
    expect(recordedAsOne([part("f1", 0), done("f2")])).toBe(false);
    expect(offersSingleRecording(contract, audio, parts)).toBe(false);
    const body = runRequest(contract, {
      values: { ärende: "Bygglov" },
      freeText: "",
      uploads: { s1: parts },
      singleRecording: new Set(),
      speakerLabels: null,
      maxSpeakers: null
    });
    expect(body.step_inputs).toEqual({ s1: { file_ids: ["f1", "f2"], single_recording: true } });
  });

  it("sends a live transcript only with the step's one file", () => {
    const choices = {
      values: { ärende: "Bygglov" },
      freeText: "",
      singleRecording: new Set<string>(),
      speakerLabels: null,
      maxSpeakers: null,
      liveTranscripts: { s1: "transcript-1" }
    };
    expect(runRequest(contract, { ...choices, uploads: { s1: [done("f1")] } }).step_inputs).toEqual(
      { s1: { file_ids: ["f1"], live_transcript_id: "transcript-1" } }
    );
    expect(
      runRequest(contract, { ...choices, uploads: { s1: [done("f1"), done("f2")] } }).step_inputs
    ).toEqual({ s1: { file_ids: ["f1", "f2"] } });
  });
});

describe("refusalTargets", () => {
  const contract = makeContract({
    form_fields: [field({ name: "ärende" })],
    steps_requiring_input: [makeInput({ step_id: "s1" }), makeInput({ step_id: "s2" })]
  });
  const refusal = (reason: string, context: Record<string, unknown>) =>
    new EneoApiError("Refused", { status: 400, reason, context });

  it("puts a field refusal at its field", () => {
    expect(
      refusalTargets(
        refusal("flow_input_required_field_missing", { field_name: "ärende" }),
        contract
      )
    ).toEqual([{ kind: "field", name: "ärende" }]);
  });

  it("puts a step refusal at each step's files", () => {
    expect(
      refusalTargets(
        refusal("flow_run_required_step_input_missing", { step_ids: ["s2", "s1"] }),
        contract
      )
    ).toEqual([
      { kind: "input", stepId: "s2" },
      { kind: "input", stepId: "s1" }
    ]);
  });

  it("puts what names nothing on the form above it", () => {
    expect(refusalTargets(refusal("flow_run_stale_version", {}), contract)).toEqual([
      { kind: "form" }
    ]);
    expect(
      refusalTargets(refusal("flow_input_invalid_option", { field_name: "borta" }), contract)
    ).toEqual([{ kind: "form" }]);
  });
});
