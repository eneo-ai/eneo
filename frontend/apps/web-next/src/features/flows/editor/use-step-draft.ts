import { useCallback, useMemo, useState } from "react";
import type { FlowStep } from "../types";

/** The fields of a step the editor changes one by one (each saved and restored on its own). */
export type DraftField =
  | "name"
  | "description"
  | "prompt"
  | "input"
  | "model_id"
  | "model_kwargs"
  | "files_from"
  | "knowledge"
  | "output"
  | "template"
  | "template_file_id"
  | "content"
  | "values"
  | "format"
  | "title"
  | "filename"
  | "purpose"
  | "tool"
  | "arguments"
  | "mode"
  | "of"
  | "expires_after_seconds"
  | "source"
  | "transcription_model_id"
  | "language"
  | "speaker_labels"
  | "max_speakers"
  | "speaker_mapping";

/** The fields a step of each kind has, in the order the form shows them. */
export const KIND_FIELDS: Record<FlowStep["kind"], DraftField[]> = {
  llm: [
    "name",
    "description",
    "prompt",
    "input",
    "model_id",
    "model_kwargs",
    "files_from",
    "knowledge",
    "output"
  ],
  compose: ["name", "description", "template"],
  document: [
    "name",
    "description",
    "template_file_id",
    "content",
    "values",
    "format",
    "title",
    "filename"
  ],
  function: ["name", "description", "purpose", "tool", "arguments", "files_from"],
  review: ["name", "description", "mode", "of", "expires_after_seconds"],
  transcribe: [
    "name",
    "description",
    "source",
    "transcription_model_id",
    "language",
    "speaker_labels",
    "max_speakers",
    "speaker_mapping"
  ]
};

/** Fields whose value is edited as JSON text; the text is kept until it parses. */
export type JsonField = "output" | "arguments";

export type JsonText = { text: string; error: string | null };

/** The editor's working copy of a step: its values, and the JSON fields as text. */
export type StepDraft = {
  step: FlowStep;
  json: Record<JsonField, JsonText>;
};

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function jsonTextOf(step: FlowStep, field: JsonField): string {
  if (field === "output") {
    return step.kind === "llm" && step.output?.type === "json"
      ? JSON.stringify(step.output.schema, null, 2)
      : "";
  }
  return step.kind === "function" ? JSON.stringify(step.arguments ?? {}, null, 2) : "";
}

function parseJsonObject(text: string): {
  value: Record<string, unknown> | null;
  error: string | null;
} {
  if (!text.trim()) return { value: null, error: "empty" };
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { value: null, error: "not_object" };
    }
    return { value: value as Record<string, unknown>, error: null };
  } catch {
    return { value: null, error: "invalid" };
  }
}

/** The step with its JSON texts applied, or null while one of them does not parse. */
export function buildStep(draft: StepDraft): FlowStep | null {
  const { step } = draft;
  if (step.kind === "llm" && step.output?.type === "json") {
    const { value } = parseJsonObject(draft.json.output.text);
    if (!value) return null;
    return { ...step, output: { type: "json", schema: value } };
  }
  if (step.kind === "function") {
    const { value } = parseJsonObject(draft.json.arguments.text);
    if (!value) return null;
    return { ...step, arguments: value };
  }
  return step;
}

/** The fields whose value differs between two steps of the same kind. */
export function changedFields(a: FlowStep, b: FlowStep): DraftField[] {
  if (a.kind !== b.kind) return KIND_FIELDS[a.kind];
  const read = (step: FlowStep, field: DraftField) => (step as Record<string, unknown>)[field];
  return KIND_FIELDS[a.kind].filter((field) => !same(read(a, field), read(b, field)));
}

function draftOf(step: FlowStep): StepDraft {
  return {
    step,
    json: {
      output: { text: jsonTextOf(step, "output"), error: null },
      arguments: { text: jsonTextOf(step, "arguments"), error: null }
    }
  };
}

/**
 * A step being edited: its working copy, what changed against the saved
 * step, and the JSON fields' validity. `update` changes values, `setJson`
 * the text of a JSON field, `restoreFrom` takes one field from another
 * version of the step (the assistant's), `reset` drops every change.
 */
export function useStepDraft(saved: FlowStep) {
  const [draft, setDraft] = useState<StepDraft>(() => draftOf(saved));

  const update = useCallback((patch: Partial<FlowStep>) => {
    setDraft((current) => ({ ...current, step: { ...current.step, ...patch } as FlowStep }));
  }, []);

  const setJson = useCallback((field: JsonField, text: string) => {
    setDraft((current) => ({
      ...current,
      json: { ...current.json, [field]: { text, error: parseJsonObject(text).error } }
    }));
  }, []);

  const restoreFrom = useCallback((field: DraftField, source: FlowStep) => {
    setDraft((current) => {
      const value = (source as Record<string, unknown>)[field];
      const step = { ...current.step, [field]: value } as FlowStep;
      const json = { ...current.json };
      if (field === "output") json.output = { text: jsonTextOf(step, "output"), error: null };
      if (field === "arguments") {
        json.arguments = { text: jsonTextOf(step, "arguments"), error: null };
      }
      return { step, json };
    });
  }, []);

  const reset = useCallback(() => setDraft(draftOf(saved)), [saved]);

  const built = useMemo(() => buildStep(draft), [draft]);
  const dirty = useMemo<DraftField[]>(() => {
    const fields = changedFields(built ?? draft.step, saved);
    const invalid: DraftField[] = [];
    if (built === null) {
      if (draft.step.kind === "llm" && draft.json.output.error) invalid.push("output");
      if (draft.step.kind === "function" && draft.json.arguments.error) invalid.push("arguments");
    }
    return [...new Set([...fields, ...invalid])];
  }, [built, draft, saved]);

  return { draft, built, dirty, update, setJson, restoreFrom, reset };
}

export type StepDraftState = ReturnType<typeof useStepDraft>;
