import { calendarDate } from "@/lib/calendar-date";
import { EneoApiError } from "@/lib/api/errors";
import type { RunContract, RunCreateRequest, RunFormField, RuntimeInput } from "./runs-api";

/**
 * The run form as the published run contract describes it: its fields in
 * order, what a value must be to be accepted, the files each step takes, what
 * blocks a run before it starts, and the request that starts it. The checks
 * mirror the core's own (`flow_run_input_payload.py`, `flow_run_step_inputs.py`)
 * so a person hears about a problem at the field before the core refuses it;
 * the core stays the authority and its refusals land on the same fields.
 */

export type FieldValue = string | string[];
export type FormValues = Record<string, FieldValue>;

/** What keeps a form field's value from being accepted. */
export type FieldProblem = "required" | "number" | "date" | "option";

/** What keeps a step's files from being accepted. */
export type InputProblem = "required" | "too_many" | "uploading" | "failed";

/** One picked file of a step, from the moment it is picked until the run starts. */
export type UploadEntry = {
  key: string;
  name: string;
  size: number;
  mimetype: string;
  state: "uploading" | "done" | "failed";
  /** The stored file, once the upload finished. */
  fileId?: string;
  /** Share of the bytes sent, 0 to 1, while uploading. */
  progress?: number;
  /** Why the upload failed, as a sentence. */
  problem?: string;
  /** The failure may pass (the network, a timeout, a busy server): the same file can be sent again. */
  retryable?: boolean;
  /**
   * A recorded part that failed and goes again by itself: when (epoch ms),
   * or null once no automatic attempt is left.
   */
  nextRetryAt?: number | null;
  /** A part of a recording made in the form, rather than a picked file. */
  recording?: RecordingPartInfo;
};

/** Which recording a recorded file belongs to, and where in it. */
export type RecordingPartInfo = {
  sessionId: string;
  /** The part's place in the recording, from 0. */
  index: number;
  durationMs: number;
};

export type UploadsByStep = Record<string, readonly UploadEntry[]>;

const MULTI_VALUE = new Set(["multiselect", "list"]);
const NUMBER = /^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$/;

export function isMultiValue(field: Pick<RunFormField, "type">): boolean {
  return MULTI_VALUE.has(field.type);
}

/** The field's label, or its technical name when it has none. */
export function fieldLabel(field: Pick<RunFormField, "label" | "name">): string {
  return field.label?.trim() || field.name;
}

/** The form fields in their display order (`order`, then as listed). */
export function orderedFields(contract: Pick<RunContract, "form_fields">): RunFormField[] {
  return (contract.form_fields ?? [])
    .map((field, index) => ({ field, index }))
    .sort(
      (a, b) => (a.field.order ?? a.index + 1) - (b.field.order ?? b.index + 1) || a.index - b.index
    )
    .map(({ field }) => field);
}

export function emptyValues(fields: readonly RunFormField[]): FormValues {
  return Object.fromEntries(
    fields.map((field) => [field.name, isMultiValue(field) ? [] : ""] as const)
  );
}

/** The runtime inputs in step order. */
export function orderedInputs(contract: Pick<RunContract, "steps_requiring_input">) {
  return [...(contract.steps_requiring_input ?? [])].sort((a, b) => a.step_order - b.step_order);
}

/**
 * A flow with neither form fields nor uploads takes one free text, sent as
 * `{ text }`, as the reference run dialog does.
 */
export function takesFreeText(
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">
): boolean {
  return (
    (contract.form_fields ?? []).length === 0 && (contract.steps_requiring_input ?? []).length === 0
  );
}

function multiValues(value: FieldValue | undefined): string[] {
  const list = Array.isArray(value) ? value : [];
  return list.map((item) => item.trim()).filter((item) => item.length > 0);
}

function singleValue(value: FieldValue | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

/** Whether the value can be sent for the field, and if not, why. */
export function fieldProblem(
  field: RunFormField,
  value: FieldValue | undefined
): FieldProblem | null {
  const options = field.options ?? [];
  if (isMultiValue(field)) {
    const values = multiValues(value);
    if (values.length === 0) return field.required ? "required" : null;
    if (field.type === "multiselect" && values.some((item) => !options.includes(item))) {
      return "option";
    }
    return null;
  }
  const text = singleValue(value);
  if (!text) return field.required ? "required" : null;
  if (field.type === "number" && !(NUMBER.test(text) && Number.isFinite(Number(text)))) {
    return "number";
  }
  if (field.type === "date" && !calendarDate(text)) return "date";
  if (field.type === "select" && !options.includes(text)) return "option";
  return null;
}

/** Every field that cannot be sent as it is, by field name. */
export function fieldProblems(
  fields: readonly RunFormField[],
  values: FormValues
): Record<string, FieldProblem> {
  const problems: Record<string, FieldProblem> = {};
  for (const field of fields) {
    const problem = fieldProblem(field, values[field.name]);
    if (problem) problems[field.name] = problem;
  }
  return problems;
}

/** The value as the core reads it; an empty optional value is sent as null ("no answer"). */
function payloadValue(field: RunFormField, value: FieldValue | undefined): unknown {
  if (isMultiValue(field)) return multiValues(value);
  const text = singleValue(value);
  if (field.type === "text") return typeof value === "string" ? value : "";
  if (!text) return null;
  return field.type === "number" ? Number(text) : text;
}

/** `input_payload_json`: the form's values by field name, or `{ text }` for free text. */
export function inputPayload(
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">,
  values: FormValues,
  freeText: string
): Record<string, unknown> {
  if (takesFreeText(contract)) return { text: freeText };
  return Object.fromEntries(
    orderedFields(contract).map((field) => [field.name, payloadValue(field, values[field.name])])
  );
}

function doneFiles(uploads: readonly UploadEntry[] | undefined): string[] {
  return (uploads ?? []).flatMap((entry) =>
    entry.state === "done" && entry.fileId ? [entry.fileId] : []
  );
}

/** The keys of a step's stored files, in order. */
export function doneKeys(uploads: readonly UploadEntry[] | undefined): string[] {
  return (uploads ?? []).flatMap((entry) =>
    entry.state === "done" && entry.fileId ? [entry.key] : []
  );
}

/**
 * Whether a step's stored files are the parts of one recording made in the
 * form: more than one, every one recorded, all in the same recording.
 */
export function recordedAsOne(uploads: readonly UploadEntry[] | undefined): boolean {
  const done = (uploads ?? []).filter((entry) => entry.state === "done" && entry.fileId);
  const [first, ...rest] = done.map((entry) => entry.recording?.sessionId);
  return first !== undefined && rest.length > 0 && rest.every((session) => session === first);
}

/** Whether a step's files can be sent, and if not, why. */
export function inputProblem(
  input: RuntimeInput,
  uploads: readonly UploadEntry[] | undefined
): InputProblem | null {
  const entries = uploads ?? [];
  if (entries.some((entry) => entry.state === "uploading")) return "uploading";
  if (entries.some((entry) => entry.state === "failed")) return "failed";
  const count = doneFiles(entries).length;
  if (input.max_files != null && count > input.max_files) return "too_many";
  if (input.required && count === 0) return "required";
  return null;
}

/** Every step whose files cannot be sent as they are, by step id. */
export function inputProblems(
  contract: Pick<RunContract, "steps_requiring_input">,
  uploads: UploadsByStep
): Record<string, InputProblem> {
  const problems: Record<string, InputProblem> = {};
  for (const input of orderedInputs(contract)) {
    const problem = inputProblem(input, uploads[input.step_id]);
    if (problem) problems[input.step_id] = problem;
  }
  return problems;
}

/** More files in all than the flow takes (`aggregate_max_files`; null is unbounded). */
export function exceedsAggregate(
  contract: Pick<RunContract, "aggregate_max_files">,
  uploads: UploadsByStep
): boolean {
  const limit = contract.aggregate_max_files;
  if (limit == null) return false;
  const total = Object.values(uploads).reduce((sum, entries) => sum + doneFiles(entries).length, 0);
  return total > limit;
}

/** Published templates that keep the flow from running until someone fixes them. */
export function blockingTemplates(contract: Pick<RunContract, "template_readiness">) {
  return (contract.template_readiness ?? []).filter(
    (item) => item.status === "needs_action" || item.status === "unavailable"
  );
}

/**
 * The flow needs speaker labels it cannot get: recording or uploading would
 * only end in `typed_io_speaker_service_unavailable`.
 */
export function speakersBlockRun(contract: Pick<RunContract, "transcription">): boolean {
  const labels = contract.transcription?.speaker_labels;
  return Boolean(labels?.required && labels.unavailable_reason);
}

/** Whether this run will label speakers, from the flow's rule and the person's choice. */
export function labelsSpeakers(
  contract: Pick<RunContract, "transcription">,
  choice: boolean | null
): boolean {
  const labels = contract.transcription?.speaker_labels;
  if (!labels) return false;
  if (labels.required) return true;
  if (labels.selectable && choice !== null) return choice;
  return labels.default;
}

/** The speaker count a run may bound: offered when speakers are labelled and the form has no count field. */
export function offersMaxSpeakers(
  contract: Pick<RunContract, "transcription">,
  speakerChoice: boolean | null
): boolean {
  const option = contract.transcription?.max_speakers;
  return Boolean(option && !option.form_field && labelsSpeakers(contract, speakerChoice));
}

/** Whether a step's files may be marked as the parts of one recording. */
export function offersSingleRecording(
  contract: Pick<RunContract, "transcription">,
  input: Pick<RuntimeInput, "input_format">,
  uploads: readonly UploadEntry[] | undefined
): boolean {
  return (
    contract.transcription?.single_recording === true &&
    input.input_format === "audio" &&
    doneFiles(uploads).length > 1 &&
    // A recording made in the form is sent as one without asking.
    !recordedAsOne(uploads)
  );
}

export type RunChoices = {
  values: FormValues;
  freeText: string;
  uploads: UploadsByStep;
  /** Steps whose files the person marked as parts of one recording. */
  singleRecording: ReadonlySet<string>;
  /** The person's speaker-label choice, or null for the flow's default. */
  speakerLabels: boolean | null;
  /** The person's speaker bound, or null to leave it to the form or the flow. */
  maxSpeakers: number | null;
  /**
   * The stored live transcript of a step whose one file is a recording the
   * live text heard whole, by step id: the run uses it instead of
   * transcribing the file again.
   */
  liveTranscripts?: Readonly<Record<string, string>>;
};

/** The request that starts the run, pinned to the contract's published version. */
export function runRequest(contract: RunContract, choices: RunChoices): RunCreateRequest {
  const stepInputs = Object.fromEntries(
    orderedInputs(contract).flatMap((input) => {
      const fileIds = doneFiles(choices.uploads[input.step_id]);
      if (fileIds.length === 0) return [];
      const uploads = choices.uploads[input.step_id];
      const single =
        (choices.singleRecording.has(input.step_id) &&
          offersSingleRecording(contract, input, uploads)) ||
        (contract.transcription?.single_recording === true &&
          input.input_format === "audio" &&
          recordedAsOne(uploads));
      const liveTranscript = fileIds.length === 1 ? choices.liveTranscripts?.[input.step_id] : null;
      return [
        [
          input.step_id,
          {
            file_ids: fileIds,
            ...(single ? { single_recording: true } : {}),
            ...(liveTranscript ? { live_transcript_id: liveTranscript } : {})
          }
        ]
      ];
    })
  );
  const labels = contract.transcription?.speaker_labels;
  return {
    expected_flow_version: contract.published_flow_version,
    input_payload_json: inputPayload(contract, choices.values, choices.freeText),
    ...(Object.keys(stepInputs).length > 0 ? { step_inputs: stepInputs } : {}),
    ...(labels?.selectable && choices.speakerLabels !== null
      ? { speaker_labels: choices.speakerLabels }
      : {}),
    ...(choices.maxSpeakers !== null && offersMaxSpeakers(contract, choices.speakerLabels)
      ? { max_speakers: choices.maxSpeakers }
      : {})
  };
}

/** Where a refusal of the run belongs: at a form field, at a step's files, or above the form. */
export type RefusalTarget =
  { kind: "field"; name: string } | { kind: "input"; stepId: string } | { kind: "form" };

/**
 * The fields a refusal of the run names in its `context`: `field_name` for a
 * form value, `step_id` or `step_ids` for a step's files. A refusal that
 * names nothing on the form, or names something the form does not have,
 * belongs above it.
 */
export function refusalTargets(
  error: unknown,
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">
): RefusalTarget[] {
  const context = error instanceof EneoApiError ? (error.context ?? {}) : {};
  const fieldName = context.field_name;
  if (
    typeof fieldName === "string" &&
    (contract.form_fields ?? []).some((field) => field.name === fieldName)
  ) {
    return [{ kind: "field", name: fieldName }];
  }
  const inputIds = new Set((contract.steps_requiring_input ?? []).map((input) => input.step_id));
  const stepIds = [
    ...(typeof context.step_id === "string" ? [context.step_id] : []),
    ...(Array.isArray(context.step_ids)
      ? context.step_ids.filter((id): id is string => typeof id === "string")
      : [])
  ].filter((id) => inputIds.has(id));
  if (stepIds.length > 0) return stepIds.map((stepId) => ({ kind: "input", stepId }));
  return [{ kind: "form" }];
}
