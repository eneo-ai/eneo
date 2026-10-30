import {
  isMultiValue,
  orderedFields,
  orderedInputs,
  takesFreeText,
  type FieldValue,
  type FormValues,
  type UploadsByStep
} from "./run-contract";
import type { RunContract, RunCreateRequest, RunFormField, RuntimeInput } from "./runs-api";

/**
 * Pure rules for the start dialog's extras: the run's own name, the audio
 * check against the length one file of an input can hold, the form as a
 * previous run filled it, and the summary shown before the run starts.
 */

/** The most characters a run's name may have, as the core counts them (code points). */
export const RUN_LABEL_MAX_LENGTH = 120;

/**
 * The name as the core takes it: one line (line breaks and control
 * characters become spaces) of at most `RUN_LABEL_MAX_LENGTH` characters.
 * `cut` says whether characters past the limit were left out.
 */
export function fitRunLabel(text: string): { label: string; cut: boolean } {
  const oneLine = text.replace(/[\p{Cc}\u2028\u2029]+/gu, " ");
  const characters = Array.from(oneLine);
  if (characters.length <= RUN_LABEL_MAX_LENGTH) return { label: oneLine, cut: false };
  return { label: characters.slice(0, RUN_LABEL_MAX_LENGTH).join(""), cut: true };
}

/** The start request with the run's name, trimmed; a blank name is left out. */
export function withRunLabel(body: RunCreateRequest, label: string): RunCreateRequest {
  const trimmed = label.trim();
  return trimmed ? { ...body, run_label: trimmed } : body;
}

/** An audio file longer than one file of the input can hold, by its measured length. */
export type OverLongAudio = { name: string; seconds: number; maxSeconds: number };

/**
 * Splits picked files into those to upload and audio files the input could
 * not transcribe because they run longer than `max_duration_seconds`. A file
 * whose length the browser cannot read goes on to the server, which checks
 * it too; only a length the browser measured refuses a file here.
 */
export async function screenAudioFiles(
  input: Pick<RuntimeInput, "input_format" | "max_duration_seconds">,
  files: readonly File[],
  measure: (file: File) => Promise<number | null>
): Promise<{ accepted: File[]; refused: OverLongAudio[] }> {
  const maxSeconds = input.max_duration_seconds;
  if (input.input_format !== "audio" || maxSeconds == null) {
    return { accepted: [...files], refused: [] };
  }
  const lengths = await Promise.all(files.map((file) => measure(file)));
  const accepted: File[] = [];
  const refused: OverLongAudio[] = [];
  files.forEach((file, index) => {
    const seconds = lengths[index];
    if (seconds != null && Math.floor(seconds) > maxSeconds) {
      refused.push({ name: file.name, seconds, maxSeconds });
    } else {
      accepted.push(file);
    }
  });
  return { accepted, refused };
}

/** A value a previous run sent, as the form field holds it now. */
function reusedValue(multi: boolean, value: unknown): FieldValue {
  const scalar = (item: unknown) =>
    typeof item === "string" || typeof item === "number" || typeof item === "boolean";
  if (multi) {
    if (Array.isArray(value)) return value.filter(scalar).map(String);
    return typeof value === "string"
      ? value
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item.length > 0)
      : [];
  }
  return scalar(value) ? String(value) : "";
}

/**
 * The form as a previous run filled it, from that run's accepted input
 * (`input_payload_json`): every field the form has now gets the value the run
 * sent for it (a list for a multi-value field) or is left empty, and a
 * free-text form gets the run's text (`freeText` is null when the run sent
 * none, so the form keeps what it has). Files are not reused; they are picked
 * again.
 */
export function reusedInput(
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">,
  payload: Record<string, unknown> | null | undefined
): { values: FormValues; freeText: string | null } {
  const previous = payload ?? {};
  const values = Object.fromEntries(
    orderedFields(contract).map(
      (field) => [field.name, reusedValue(isMultiValue(field), previous[field.name])] as const
    )
  );
  const text = previous.text;
  return {
    values,
    freeText: takesFreeText(contract) && typeof text === "string" ? text : null
  };
}

/** Whether the form has anything a previous run's input could fill: fields, or a free text. */
export function takesReusableInput(
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">
): boolean {
  return (contract.form_fields ?? []).length > 0 || takesFreeText(contract);
}

/** What the run is sent, as the summary before starting lists it. */
export type StartSummary = {
  /** The run's name, or null when it has none. */
  runLabel: string | null;
  /** The form fields given a value, in form order, each value as one line of text. */
  fields: { field: RunFormField; value: string }[];
  /** The free text, or null when the form takes none or it is blank. */
  freeText: string | null;
  /** The stored files of each step that has any, in step order. */
  files: { input: RuntimeInput; files: { key: string; name: string; size: number }[] }[];
};

function shownValue(field: RunFormField, value: FieldValue | undefined): string {
  if (isMultiValue(field)) {
    const items = Array.isArray(value) ? value : [];
    return items
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
      .join(", ");
  }
  return typeof value === "string" ? value.trim() : "";
}

/**
 * The summary before starting: the run's name, the fields given a value, the
 * free text and the files, as the start request will send them. Empty
 * optional fields are left out, as they carry no answer.
 */
export function startSummary(
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">,
  choices: { runLabel: string; values: FormValues; freeText: string; uploads: UploadsByStep }
): StartSummary {
  const fields = orderedFields(contract).flatMap((field) => {
    const value = shownValue(field, choices.values[field.name]);
    return value ? [{ field, value }] : [];
  });
  const freeText = takesFreeText(contract) ? choices.freeText.trim() : "";
  const files = orderedInputs(contract).flatMap((input) => {
    const stored = (choices.uploads[input.step_id] ?? []).flatMap((entry) =>
      entry.state === "done" && entry.fileId
        ? [{ key: entry.key, name: entry.name, size: entry.size }]
        : []
    );
    return stored.length > 0 ? [{ input, files: stored }] : [];
  });
  return {
    runLabel: choices.runLabel.trim() || null,
    fields,
    freeText: freeText || null,
    files
  };
}

/** Whether the summary has nothing to list. */
export function summaryIsEmpty(summary: StartSummary): boolean {
  return (
    summary.runLabel === null &&
    summary.fields.length === 0 &&
    summary.freeText === null &&
    summary.files.length === 0
  );
}
