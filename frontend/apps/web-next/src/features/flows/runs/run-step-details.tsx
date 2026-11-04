import { LazyCollapsible } from "@/components/astryx/collapsible";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { CopyButton } from "./run-copy";
import { JsonValue } from "./run-json";
import type { RunStep } from "./runs-api";

/** What the core keeps beside the settings for itself: how a step ran, its ids and hashes. */
const CORE_KEYS = new Set([
  "model_id",
  "parameter_semantics",
  "mode",
  "skipped",
  "long_material_mode",
  "runtime_input_execution_mode",
  "item_map_execution_mode",
  "template_file_id",
  "template_asset_id",
  "template_checksum",
  "source_run_id"
]);

/** Settings by the app's word for them; one the app does not know keeps the core's name. */
const SETTING_LABELS: Record<string, string> = {
  model_name: "model",
  provider: "provider",
  temperature: "temperature",
  top_p: "top_p",
  top_k: "top_k",
  reasoning_effort: "reasoning_effort",
  verbosity: "verbosity",
  presence_penalty: "presence_penalty",
  frequency_penalty: "frequency_penalty",
  response_format: "flow_run_setting_response_format",
  per_source_call_count: "flow_run_setting_per_source_calls",
  per_item_call_count: "flow_run_setting_per_item_calls"
};

function isUnset(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (typeof value === "object" && Object.keys(value).length === 0)
  );
}

/** The settings a step ran with: the core lists every one, set or not. */
function modelSettings(parameters: RunStep["model_parameters_json"]) {
  return Object.entries(parameters ?? {}).filter(
    ([key, value]) => !CORE_KEYS.has(key) && !isUnset(value)
  );
}

/** Whether the step recorded the prompt it sent or the model settings it used. */
export function hasPromptDetails(
  result: Pick<RunStep, "effective_prompt" | "model_parameters_json">
): boolean {
  return (
    Boolean(result.effective_prompt?.trim()) ||
    modelSettings(result.model_parameters_json).length > 0
  );
}

/**
 * What the step sent its model: the prompt as it was put together for this
 * run (a stored prefix when the core cut it) and the model settings in
 * force, by name and only those set. Part of the step results already read;
 * rendered only when opened, since a prompt can be long.
 */
export function StepPromptDetails({
  result
}: {
  result: Pick<
    RunStep,
    "effective_prompt" | "effective_prompt_truncated" | "model_parameters_json"
  >;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  if (!hasPromptDetails(result)) return null;
  const prompt = result.effective_prompt?.trim() ? result.effective_prompt : null;
  const settings = modelSettings(result.model_parameters_json);
  return (
    <LazyCollapsible
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={
        <span className="block py-1.5 text-sm font-medium">
          {t("flow_run_extras_prompt_heading")}
        </span>
      }
    >
      <div className="flex flex-col gap-3 pt-2">
        {prompt ? (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
              <p className="text-ax-text text-sm font-medium">{t("flow_run_extras_prompt")}</p>
              <CopyButton label={t("flow_run_more_copy_prompt")} value={prompt} />
            </div>
            <pre className="bg-ax-sunken rounded-ax-inner text-ax-text max-h-96 overflow-auto p-2 text-xs break-words whitespace-pre-wrap">
              {prompt}
            </pre>
            {result.effective_prompt_truncated ? (
              <p className="text-ax-text-secondary text-xs">
                {t("flow_run_extras_prompt_truncated")}
              </p>
            ) : null}
          </div>
        ) : null}
        {settings.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-ax-text text-sm font-medium">
              {t("flow_run_extras_model_parameters")}
            </p>
            <JsonValue
              value={Object.fromEntries(
                settings.map(([key, value]) => {
                  const label = SETTING_LABELS[key];
                  return [label ? t(label) : key, value];
                })
              )}
            />
          </div>
        ) : null}
      </div>
    </LazyCollapsible>
  );
}
