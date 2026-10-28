import { describe, expect, it } from "vitest";
import { makeCheckpoint } from "./run-fixtures";
import {
  changedFields,
  draftChanged,
  editedValueOf,
  REJECT_REASON_MAX_LENGTH,
  rejectReasonProblem,
  reviewDraftOf,
  reviewExpired,
  reviewOptions
} from "./review-draft";

const NOW = Date.parse("2026-10-22T08:00:00Z");

describe("reviewDraftOf", () => {
  it("edits a text step as text", () => {
    expect(reviewDraftOf(makeCheckpoint())).toEqual({
      kind: "text",
      text: "Hej Anna, tack för ditt brev."
    });
  });

  it("edits a flat JSON object field by field, and other JSON as JSON text", () => {
    const flat = makeCheckpoint({
      output_type: "json",
      current_payload_json: { structured: { titel: "Svar", antal: 3, klar: false, not: null } }
    });
    expect(reviewDraftOf(flat)).toEqual({
      kind: "fields",
      fields: [
        { name: "titel", kind: "string", value: "Svar" },
        { name: "antal", kind: "number", value: "3" },
        { name: "klar", kind: "boolean", value: "false" },
        { name: "not", kind: "null", value: "" }
      ]
    });
    const nested = makeCheckpoint({
      output_type: "json",
      current_payload_json: { structured: { punkter: ["a", "b"] } }
    });
    expect(reviewDraftOf(nested).kind).toBe("json");
  });

  it("names the speakers of a speaker mapping one by one, keeping what else the step proposed", () => {
    const checkpoint = makeCheckpoint({
      output_type: "json",
      current_payload_json: {
        structured: {
          speakers: [
            { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "Säger sitt namn" },
            { label: "SPEAKER_01", name: null, confidence: "low", evidence: "" }
          ]
        }
      }
    });
    const draft = reviewDraftOf(checkpoint);
    expect(draft).toMatchObject({
      kind: "speakers",
      speakers: [
        { label: "SPEAKER_00", name: "Anna" },
        { label: "SPEAKER_01", name: "" }
      ]
    });
    if (draft.kind !== "speakers") return;
    const edited = editedValueOf({
      ...draft,
      speakers: draft.speakers.map((speaker) => ({ ...speaker, name: speaker.name || " Bo " }))
    });
    expect(edited).toEqual({
      ok: true,
      value: {
        speakers: [
          { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "Säger sitt namn" },
          { label: "SPEAKER_01", name: "Bo", confidence: "low", evidence: "" }
        ]
      }
    });
  });

  it("edits nested JSON its output contract describes as a form built from the contract", () => {
    const contract = {
      type: "object",
      properties: { punkter: { type: "array", items: { type: "string" } } }
    };
    const checkpoint = makeCheckpoint({
      output_type: "json",
      output_contract: contract,
      current_payload_json: { structured: { punkter: ["a", "b"] } }
    });
    expect(reviewDraftOf(checkpoint)).toEqual({
      kind: "structured",
      schema: contract,
      value: { punkter: ["a", "b"] }
    });
    // A value the contract does not describe stays JSON text.
    const mismatched = makeCheckpoint({
      output_type: "json",
      output_contract: contract,
      current_payload_json: { structured: ["a", "b"] }
    });
    expect(reviewDraftOf(mismatched).kind).toBe("json");
  });

  it("reviews a document step as its file", () => {
    expect(reviewDraftOf(makeCheckpoint({ output_type: "pdf" })).kind).toBe("file");
  });
});

describe("editedValueOf", () => {
  it("sends a text step's string and a JSON step's value with its types back", () => {
    expect(editedValueOf({ kind: "text", text: "Ny text" })).toEqual({
      ok: true,
      value: "Ny text"
    });
    expect(
      editedValueOf({
        kind: "fields",
        fields: [
          { name: "antal", kind: "number", value: " 4 " },
          { name: "klar", kind: "boolean", value: "true" },
          { name: "not", kind: "null", value: "" }
        ]
      })
    ).toEqual({ ok: true, value: { antal: 4, klar: true, not: null } });
    expect(editedValueOf({ kind: "json", text: '["a"]' })).toEqual({ ok: true, value: ["a"] });
    expect(
      editedValueOf({ kind: "structured", schema: {}, value: { punkter: [{ antal: 2 }] } })
    ).toEqual({ ok: true, value: { punkter: [{ antal: 2 }] } });
  });

  it("names the field that is not a number, and JSON text that is not an object or list", () => {
    expect(
      editedValueOf({ kind: "fields", fields: [{ name: "antal", kind: "number", value: "fyra" }] })
    ).toEqual({ ok: false, problem: { field: "antal", reason: "number" } });
    expect(editedValueOf({ kind: "json", text: "{" })).toEqual({
      ok: false,
      problem: { field: null, reason: "json" }
    });
    expect(editedValueOf({ kind: "json", text: "12" })).toEqual({
      ok: false,
      problem: { field: null, reason: "json_kind" }
    });
  });
});

describe("changedFields", () => {
  it("names the fields whose value differs from the step's own output, by what would be sent", () => {
    const fields = [
      { name: "mottagare", kind: "string" as const, value: "Bo" },
      { name: "antal", kind: "number" as const, value: "2" },
      { name: "klar", kind: "boolean" as const, value: "true" },
      { name: "notering", kind: "null" as const, value: "" },
      { name: "ny", kind: "string" as const, value: "x" }
    ];
    expect([
      ...changedFields(fields, { mottagare: "Anna", antal: 2, klar: true, notering: null })
    ]).toEqual(["mottagare", "ny"]);
  });

  it("counts a value that cannot be sent as changed", () => {
    expect([
      ...changedFields([{ name: "antal", kind: "number", value: "två" }], { antal: 2 })
    ]).toEqual(["antal"]);
  });
});

describe("draftChanged", () => {
  it("sees a change only when the reviewer made one", () => {
    const checkpoint = makeCheckpoint();
    expect(draftChanged(reviewDraftOf(checkpoint), checkpoint)).toBe(false);
    expect(draftChanged({ kind: "text", text: "Annat" }, checkpoint)).toBe(true);
  });
});

describe("reviewOptions", () => {
  it("lets a reviewer decide and edit an open checkpoint in edit mode before its deadline", () => {
    expect(reviewOptions(makeCheckpoint(), true, NOW)).toEqual({
      canDecide: true,
      canEdit: true,
      canResume: false,
      expired: false
    });
  });

  it("decides without editing in view mode, and neither without the permission", () => {
    expect(reviewOptions(makeCheckpoint({ review_mode: "view" }), true, NOW).canEdit).toBe(false);
    expect(reviewOptions(makeCheckpoint(), false, NOW).canDecide).toBe(false);
  });

  it("closes the decision at the deadline but still resumes an approval made in time", () => {
    const expires_at = "2026-10-28T08:00:30Z";
    const late = Date.parse("2026-10-29T00:00:00Z");
    expect(reviewExpired(makeCheckpoint({ expires_at }), late)).toBe(true);
    expect(reviewOptions(makeCheckpoint({ expires_at }), true, late).canDecide).toBe(false);
    const approved = makeCheckpoint({
      state: "approved",
      approved_at: "2026-10-27T08:00:00Z",
      expires_at
    });
    expect(reviewOptions(approved, true, late)).toMatchObject({
      canDecide: false,
      canResume: true
    });
  });

  it("treats a checkpoint the core marked expired as expired whatever the clock says", () => {
    expect(reviewExpired(makeCheckpoint({ state: "expired" }), NOW)).toBe(true);
  });
});

describe("rejectReasonProblem", () => {
  it("asks for a reason that is not blank", () => {
    expect(rejectReasonProblem("")).toBe("required");
    expect(rejectReasonProblem("  \n ")).toBe("required");
    expect(rejectReasonProblem("Fel mottagare")).toBeNull();
  });

  it("counts the trimmed reason in code points, as the core does", () => {
    expect(REJECT_REASON_MAX_LENGTH).toBe(1024);
    expect(rejectReasonProblem(`  ${"å".repeat(1024)}  `)).toBeNull();
    expect(rejectReasonProblem("x".repeat(1025))).toBe("too_long");
    // An emoji outside the basic plane is one code point but two UTF-16 units.
    expect(rejectReasonProblem("😀".repeat(1024))).toBeNull();
    expect(rejectReasonProblem("😀".repeat(1025))).toBe("too_long");
  });
});
