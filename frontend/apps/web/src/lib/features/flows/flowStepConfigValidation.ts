import type { FlowStep } from "@eneo/eneo-js";
import { getTemplateFillOutputConfig } from "./templateFillConfig";
import { createDefaultHttpConfig } from "./components/http/httpConfigDefaults";
import { parseHttpAuthoredConfig } from "./components/http/httpConfigTypes";

/** Matches the synthetic token for a reference to a since-deleted step. */
export const DELETED_STEP_TOKEN = /\{\{step_\d+_deleted/;

/**
 * Per-step configuration validation: a template_fill step needs a template
 * asset, and an HTTP input/output step needs a URL. Returned keys are namespaced
 * with `prefix` so the caller can replace exactly its own error slice.
 */
export function computeStepConfigValidationIssues(
  steps: FlowStep[],
  prefix: string
): Map<string, string[]> {
  const entries = new Map<string, string[]>();
  for (const step of steps) {
    if (step.output_mode === "template_fill") {
      const config = getTemplateFillOutputConfig(step);
      if (!config.template_asset_id) {
        entries.set(`${prefix}template_fill_no_template:${step.step_order}`, [
          "template_fill_no_template"
        ]);
      }
    }
    if (step.output_mode === "http_post") {
      const config = parseHttpAuthoredConfig(
        step.output_config,
        createDefaultHttpConfig("output", "POST")
      );
      if (!config.url.trim()) {
        entries.set(`${prefix}http_missing_url:${step.step_order}`, ["http_missing_url"]);
      }
    }
    if (step.input_source === "http_get" || step.input_source === "http_post") {
      const config = parseHttpAuthoredConfig(
        step.input_config,
        createDefaultHttpConfig("input", step.input_source === "http_get" ? "GET" : "POST")
      );
      if (!config.url.trim()) {
        entries.set(`${prefix}http_missing_url:${step.step_order}`, ["http_missing_url"]);
      }
    }
  }
  return entries;
}

/**
 * True if any step still references a deleted step — either in its
 * input_bindings.question or in its cached assistant prompt text. The caller
 * pre-fetches the cached prompt texts (keyed by assistant id) so this stays pure.
 */
export function hasDeletedStepReferences(
  steps: FlowStep[],
  cachedPromptTextByAssistantId: Map<string, string>
): boolean {
  for (const step of steps) {
    const bindings = step.input_bindings as { question?: string } | null | undefined;
    if (typeof bindings?.question === "string" && DELETED_STEP_TOKEN.test(bindings.question)) {
      return true;
    }
    const text = cachedPromptTextByAssistantId.get(step.assistant_id) ?? "";
    if (DELETED_STEP_TOKEN.test(text)) return true;
  }
  return false;
}
