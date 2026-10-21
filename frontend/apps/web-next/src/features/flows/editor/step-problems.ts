import type { DraftField } from "./use-step-draft";

/** A problem the validator reported, placed at a field when it names one of this step's. */
export type PlacedProblem = { field: DraftField | null; text: string };

// The validator prefixes a step's problems with "step '<key>' <field>[.<sub>]:".
const STEP_PROBLEM = /^step '([^']+)' ([a-z_]+)(?:\.[a-z_]+)*:?\s*/;

const FIELDS = new Set<string>([
  "name",
  "description",
  "prompt",
  "input",
  "model_id",
  "model_kwargs",
  "files_from",
  "knowledge",
  "processing",
  "output",
  "template",
  "template_file_id",
  "content",
  "values",
  "format",
  "title",
  "filename",
  "purpose",
  "tool",
  "arguments",
  "mode",
  "of",
  "expires_after_seconds",
  "source",
  "transcription_model_id",
  "language",
  "speaker_labels",
  "max_speakers",
  "speaker_mapping"
]);

/**
 * Places the validator's problems: one about this step and a known field
 * goes to that field (its prefix dropped), everything else stays general.
 */
export function placeProblems(problems: string[], stepKey: string): PlacedProblem[] {
  return problems.map((text) => {
    const match = STEP_PROBLEM.exec(text);
    if (!match || match[1] !== stepKey) return { field: null, text };
    const field = match[2]!;
    if (!FIELDS.has(field)) return { field: null, text };
    const rest = text.slice(match[0].length).trim();
    return {
      field: field as DraftField,
      text: rest ? rest[0]!.toUpperCase() + rest.slice(1) : text
    };
  });
}
