"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { CopyButton } from "./run-copy";
import { JsonValue } from "./run-json";
import type { RunStep } from "./runs-api";

/** Whether the step recorded the prompt it sent or the model settings it used. */
export function hasPromptDetails(
  result: Pick<RunStep, "effective_prompt" | "model_parameters_json">
): boolean {
  return (
    Boolean(result.effective_prompt?.trim()) ||
    Object.keys(result.model_parameters_json ?? {}).length > 0
  );
}

/**
 * What the step sent its model: the prompt as it was put together for this
 * run (a stored prefix when the core cut it) and the model settings in
 * force. Part of the step results already read; rendered only when opened,
 * since a prompt can be long.
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
  const parameters = result.model_parameters_json ?? {};
  return (
    <Collapsible
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={<span className="text-sm font-medium">{t("flow_run_extras_prompt_heading")}</span>}
    >
      {open ? (
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
          {Object.keys(parameters).length > 0 ? (
            <div className="flex flex-col gap-1">
              <p className="text-ax-text text-sm font-medium">
                {t("flow_run_extras_model_parameters")}
              </p>
              <JsonValue value={parameters} />
            </div>
          ) : null}
        </div>
      ) : null}
    </Collapsible>
  );
}
