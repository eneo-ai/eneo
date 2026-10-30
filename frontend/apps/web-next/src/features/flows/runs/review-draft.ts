import { formFits, schemaOf, type ReviewSchema, type ReviewValue } from "./review-structured";
import type { ReviewCheckpoint } from "./runs-api";

/**
 * A reviewer's working copy of a paused step's output, and what may be done
 * with the checkpoint, from its state, mode, output type and deadline as the
 * core reports them. Pure; the review panel renders it.
 */

type Scalar = string | number | boolean | null;

/** One field of a flat structured output, edited as text. */
export type DraftField = {
  name: string;
  kind: "string" | "number" | "boolean" | "null";
  value: string;
};

/** One diarized speaker of a speaker-mapping step, with the name the step proposed. */
export type DraftSpeaker = {
  label: string;
  name: string;
  /** The rest of the row as the step proposed it (confidence, evidence), sent back unchanged. */
  rest: Record<string, unknown>;
};

export type ReviewDraft =
  | { kind: "text"; text: string }
  /** A speaker mapping (`{ speakers: [{ label, name, … }] }`): one name per speaker. */
  | { kind: "speakers"; speakers: DraftSpeaker[]; rest: Record<string, unknown> }
  /** A flat JSON object: one control per field. */
  | { kind: "fields"; fields: DraftField[] }
  /** Nested JSON the step's output contract describes: a form built from the contract. */
  | { kind: "structured"; schema: ReviewSchema; value: ReviewValue }
  /** Any other JSON value: edited as JSON text. */
  | { kind: "json"; text: string }
  /** A document step (PDF, Word): reviewed as its file, never edited. */
  | { kind: "file" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function scalarKind(value: unknown): DraftField["kind"] | null {
  if (value === null) return "null";
  if (typeof value === "string") return "string";
  if (typeof value === "number" && Number.isFinite(value)) return "number";
  if (typeof value === "boolean") return "boolean";
  return null;
}

/** The speakers of a speaker mapping, or null when the value is not one. */
function speakerRows(value: unknown): DraftSpeaker[] | null {
  if (!isRecord(value) || !Array.isArray(value.speakers) || value.speakers.length === 0) {
    return null;
  }
  const rows: DraftSpeaker[] = [];
  for (const item of value.speakers) {
    if (!isRecord(item) || typeof item.label !== "string") return null;
    const { label, name, ...rest } = item;
    rows.push({ label, name: typeof name === "string" ? name : "", rest });
  }
  return rows;
}

/** The working copy of what the checkpoint holds now. */
export function reviewDraftOf(
  checkpoint: Pick<ReviewCheckpoint, "output_type" | "current_payload_json" | "output_contract">
): ReviewDraft {
  const payload = checkpoint.current_payload_json ?? {};
  if (checkpoint.output_type === "text") {
    return { kind: "text", text: typeof payload.text === "string" ? payload.text : "" };
  }
  if (checkpoint.output_type === "json") {
    const value = payload.structured ?? {};
    const speakers = speakerRows(value);
    if (speakers && isRecord(value)) {
      const rest = Object.fromEntries(Object.entries(value).filter(([key]) => key !== "speakers"));
      return { kind: "speakers", speakers, rest };
    }
    if (isRecord(value) && Object.keys(value).length > 0) {
      const fields = Object.entries(value).map(([name, item]) => {
        const kind = scalarKind(item);
        return kind ? { name, kind, value: item === null ? "" : String(item) } : null;
      });
      if (fields.every((field): field is DraftField => field !== null)) {
        return { kind: "fields", fields };
      }
    }
    if (formFits(checkpoint.output_contract, value)) {
      return { kind: "structured", schema: schemaOf(checkpoint.output_contract), value };
    }
    return { kind: "json", text: JSON.stringify(value, null, 2) };
  }
  return { kind: "file" };
}

export type EditedValue = string | Record<string, unknown> | unknown[];

/** Why the working copy cannot be sent: a field that is not a number, or text that is not JSON. */
export type DraftProblem = { field: string | null; reason: "number" | "json" | "json_kind" };

function fieldValue(field: DraftField): { ok: true; value: Scalar } | { ok: false } {
  const text = field.value.trim();
  switch (field.kind) {
    case "number": {
      if (!text) return { ok: true, value: null };
      const number = Number(text);
      return Number.isFinite(number) ? { ok: true, value: number } : { ok: false };
    }
    case "boolean":
      return { ok: true, value: field.value === "true" };
    case "null":
      return { ok: true, value: text ? field.value : null };
    case "string":
      return { ok: true, value: field.value };
  }
}

/**
 * The value the core's edit endpoint takes (`edited_value`): the corrected
 * output itself, a string for a text step and an object or array for a JSON
 * step. The core validates it against the step's output contract.
 */
export function editedValueOf(
  draft: ReviewDraft
): { ok: true; value: EditedValue } | { ok: false; problem: DraftProblem } {
  switch (draft.kind) {
    case "text":
      return { ok: true, value: draft.text };
    case "speakers":
      return {
        ok: true,
        value: {
          ...draft.rest,
          speakers: draft.speakers.map((speaker) => ({
            ...speaker.rest,
            label: speaker.label,
            name: speaker.name.trim() || null
          }))
        }
      };
    case "fields": {
      const value: Record<string, Scalar> = {};
      for (const field of draft.fields) {
        const parsed = fieldValue(field);
        if (!parsed.ok) return { ok: false, problem: { field: field.name, reason: "number" } };
        value[field.name] = parsed.value;
      }
      return { ok: true, value };
    }
    case "structured":
      return { ok: true, value: draft.value as EditedValue };
    case "json": {
      let parsed: unknown;
      try {
        parsed = JSON.parse(draft.text);
      } catch {
        return { ok: false, problem: { field: null, reason: "json" } };
      }
      if (typeof parsed !== "object" || parsed === null) {
        return { ok: false, problem: { field: null, reason: "json_kind" } };
      }
      return { ok: true, value: parsed as EditedValue };
    }
    case "file":
      return { ok: false, problem: { field: null, reason: "json_kind" } };
  }
}

/**
 * The flat fields whose value differs from the step's own output before any
 * review changed it (`original`), compared by the value an edit would send.
 * A field the original does not have, or one that cannot be sent as it is,
 * differs.
 */
export function changedFields(
  fields: readonly DraftField[],
  original: Readonly<Record<string, unknown>>
): ReadonlySet<string> {
  const changed = new Set<string>();
  for (const field of fields) {
    const parsed = fieldValue(field);
    if (!(field.name in original) || !parsed.ok || parsed.value !== original[field.name]) {
      changed.add(field.name);
    }
  }
  return changed;
}

/** Whether the reviewer changed the output from what the checkpoint holds. */
export function draftChanged(
  draft: ReviewDraft,
  checkpoint: Pick<ReviewCheckpoint, "output_type" | "current_payload_json" | "output_contract">
): boolean {
  return JSON.stringify(draft) !== JSON.stringify(reviewDraftOf(checkpoint));
}

const OPEN_STATES = new Set(["awaiting_review", "edited"]);

/** The review deadline passed, by the core's state or by its `expires_at` against `now`. */
export function reviewExpired(
  checkpoint: Pick<ReviewCheckpoint, "state" | "expired_at" | "expires_at">,
  now: number
): boolean {
  if (checkpoint.state === "expired" || checkpoint.expired_at) return true;
  if (!checkpoint.expires_at) return false;
  const deadline = Date.parse(checkpoint.expires_at);
  return Number.isFinite(deadline) && now >= deadline;
}

export type ReviewOptions = {
  /** Still open for a decision, before its deadline. */
  canDecide: boolean;
  /** The output may be changed (`review_mode` edit on a text or JSON step). */
  canEdit: boolean;
  /** Approved through the split approve call; the run waits to be resumed. */
  canResume: boolean;
  expired: boolean;
};

/**
 * What the reviewer may do: decide while the checkpoint is open and its
 * deadline has not passed; edit only in edit mode and only text or JSON;
 * resume an approved checkpoint, which the core allows past the deadline.
 * `mayReview` is the caller's permission to review flows.
 */
export function reviewOptions(
  checkpoint: Pick<
    ReviewCheckpoint,
    "state" | "expired_at" | "expires_at" | "review_mode" | "output_type"
  >,
  mayReview: boolean,
  now: number
): ReviewOptions {
  const expired = reviewExpired(checkpoint, now);
  const canDecide = mayReview && OPEN_STATES.has(checkpoint.state) && !expired;
  return {
    canDecide,
    canEdit:
      canDecide &&
      checkpoint.review_mode === "edit" &&
      (checkpoint.output_type === "text" || checkpoint.output_type === "json"),
    canResume: mayReview && checkpoint.state === "approved",
    expired
  };
}

/**
 * The most characters a rejection reason may have, as the reject request's
 * `reason` declares (`maxLength`). The core counts the trimmed reason in
 * code points, so the check here does too.
 */
export const REJECT_REASON_MAX_LENGTH = 1024;

/** Why a rejection reason would be refused, or null when it would be accepted. */
export function rejectReasonProblem(reason: string): "required" | "too_long" | null {
  const trimmed = reason.trim();
  if (!trimmed) return "required";
  return Array.from(trimmed).length > REJECT_REASON_MAX_LENGTH ? "too_long" : null;
}
