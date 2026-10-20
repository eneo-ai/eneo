"use client";

import { useTranslations } from "next-intl";
import { formatDuration, functionPurposeLabel, stepKindLabel } from "./flow-labels";
import type { FlowStep } from "./types";

/**
 * Names for the ids a definition carries. The panel builds one from the
 * space (its models and knowledge); without it the ids show as they are.
 */
export type FlowNames = {
  modelName?: (id: string) => string | null;
  transcriptionModelName?: (id: string) => string | null;
  collectionName?: (id: string) => string | null;
  websiteName?: (id: string) => string | null;
  fileName?: (id: string) => string | null;
};

export const NO_NAMES: FlowNames = {};

export const shortId = (id: string) => (id.length > 12 ? `${id.slice(0, 8)}…` : id);

/** An id as its name, or shortened in monospace when no name is known. */
export function Named({ id, resolve }: { id: string; resolve?: (id: string) => string | null }) {
  const name = resolve?.(id) ?? null;
  return name ? <>{name}</> : <span className="font-mono text-xs">{shortId(id)}</span>;
}

type Translate = ReturnType<typeof useTranslations>;

/**
 * One line that says what a step does with, for the navigator: the model
 * and output kind, the review mode, the document format and template, or
 * the transcription model.
 */
export function stepSummary(step: FlowStep, names: FlowNames, t: Translate): string {
  switch (step.kind) {
    case "llm": {
      const model = step.model_id
        ? (names.modelName?.(step.model_id) ?? shortId(step.model_id))
        : t("flow_param_model_default");
      const output =
        step.output?.type === "json" ? t("flow_step_summary_json") : t("flow_step_summary_text");
      return `${model} · ${output}`;
    }
    case "compose":
      return t("flow_param_template");
    case "document": {
      const format = (step.format ?? "docx").toUpperCase();
      const template = step.template_file_id
        ? (names.fileName?.(step.template_file_id) ?? shortId(step.template_file_id))
        : null;
      return template ? `${format} · ${template}` : format;
    }
    case "function":
      return `${functionPurposeLabel(step.purpose, t)} · ${step.tool}`;
    case "review":
      return step.mode === "view"
        ? t("flow_step_summary_review_view")
        : t("flow_step_summary_review_edit");
    case "transcribe":
      return step.transcription_model_id
        ? (names.transcriptionModelName?.(step.transcription_model_id) ??
            shortId(step.transcription_model_id))
        : t("flow_param_model_default");
  }
}

/** "Modell", "Granskning · 7 dagar", "Dokument · DOCX": the kind line under a step's name in the navigator. */
export function stepKindLine(step: FlowStep, t: Translate): string {
  const kind = stepKindLabel(step.kind, t);
  switch (step.kind) {
    case "review":
      return step.expires_after_seconds
        ? `${kind} · ${formatDuration(step.expires_after_seconds, t)}`
        : kind;
    case "document":
      return `${kind} · ${(step.format ?? "docx").toUpperCase()}`;
    default:
      return kind;
  }
}
